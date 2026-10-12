"""Employee Attendance & Analytics API, contract v2.0."""
import os, re, math
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Literal
from fastapi import FastAPI, HTTPException, Query, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from bson import ObjectId

load_dotenv()
IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), tz_aware=True, serverSelectionTimeoutMS=3000)
db = client[os.getenv("MONGO_DB", "attendance_db")]
app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")
PRESENT = ["PRESENT", "WFH", "ON_DUTY"]
STATUSES = PRESENT + ["ABSENT", "LEAVE"]


def now_utc(): return datetime.now(UTC).replace(microsecond=0)
def dt_utc(value):
    if value is None: return None
    if value.tzinfo is None: return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
def epoch_ms(value):
    value = dt_utc(value)
    return int(value.timestamp() * 1000) if value else None
def from_ms(value):
    if value is None: return None
    if type(value) is not int or not 100_000_000_000 <= value <= 4_102_444_800_000:
        raise ValueError("timestamp must be epoch milliseconds")
    return datetime.fromtimestamp(value / 1000, UTC).replace(microsecond=0)
def money(value, places=2):
    if value is None: return None
    return float(Decimal(str(value)).quantize(Decimal('1.' + '0'*places), rounding=ROUND_HALF_UP))
def iso_date(value, label="date"):
    try: return date.fromisoformat(value).isoformat()
    except Exception: raise HTTPException(422, f"{label} must be YYYY-MM-DD")
def month_bounds(month):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        raise HTTPException(422, "month must be YYYY-MM")
    y, m = map(int, month.split('-')); start=date(y,m,1); end=date(y+1,1,1) if m==12 else date(y,m+1,1)
    return start.isoformat(), (end-timedelta(days=1)).isoformat(), end.isoformat()
def day_count_working(start, end):
    # Inclusive weekday count in O(1), with no per-day Python loop.
    a=date.fromisoformat(start); b=date.fromisoformat(end)
    n=(b-a).days+1
    if n <= 0: return 0
    weeks, rem=divmod(n,7)
    return weeks*5 + sum(1 for i in range(rem) if (a.weekday()+i)%7 < 5)
def shift_minutes(s):
    try:
        h,m=map(int,s.split(':'))
        if not (0<=h<=23 and 0<=m<=59): raise ValueError()
        return h*60+m
    except Exception: raise HTTPException(422, "shift time must be HH:MM")
def attendance_date(punch_in, emp):
    local=dt_utc(punch_in).astimezone(IST); d=local.date()
    if shift_minutes(emp['shift_end']) <= shift_minutes(emp['shift_start']) and local.hour*60+local.minute < shift_minutes(emp['shift_end']):
        d -= timedelta(days=1)
    return d.isoformat()
def late_minutes(punch_in, emp):
    local=dt_utc(punch_in).astimezone(IST); start=shift_minutes(emp['shift_start']); actual=local.hour*60+local.minute
    # Early-morning punches on an overnight shift belong to the next shift day.
    if shift_minutes(emp['shift_end']) <= start and actual < shift_minutes(emp['shift_end']): actual += 1440
    # whole seconds matter for the strict 10-minute grace boundary
    delta=(actual-start)*60+local.second
    return max(0, delta//60) if delta > 600 else 0
def derived(punch_in, punch_out, emp):
    if not punch_in: return {"late_minutes":0,"work_hours":None,"overtime_minutes":0,"half_day":False}
    late=late_minutes(punch_in,emp)
    if not punch_out: return {"late_minutes":late,"work_hours":None,"overtime_minutes":0,"half_day":False}
    seconds=int((dt_utc(punch_out)-dt_utc(punch_in)).total_seconds())
    hours=money(Decimal(seconds)/Decimal(3600),2)
    local_out=dt_utc(punch_out).astimezone(IST); end=shift_minutes(emp['shift_end'])
    start=shift_minutes(emp['shift_start']); shift_date=date.fromisoformat(attendance_date(punch_in,emp))
    end_date=shift_date + (timedelta(days=1) if end<=start else timedelta(days=0))
    end_dt=datetime.combine(end_date,time(end//60,end%60),IST).astimezone(UTC)
    overtime=max(0,int((dt_utc(punch_out)-end_dt).total_seconds()//60))
    if overtime < 30: overtime=0
    return {"late_minutes":late,"work_hours":hours,"overtime_minutes":overtime,"half_day":hours<4.50}
def serialize_doc(doc):
    if not doc: return doc
    d=dict(doc); oid=d.pop('_id',None); d['id']=str(oid) if oid else d.get('id')
    for key in ('punch_in','punch_out'):
        if key in d: d[key]=epoch_ms(d[key])
    for h in d.get('history',[]):
        h['at']=epoch_ms(h.get('at'))
        for field, change in h.get('changes',{}).items():
            if field in ('punch_in','punch_out'):
                change['from']=epoch_ms(change.get('from')); change['to']=epoch_ms(change.get('to'))
    d.pop('id',None) if d.get('id') is None else None
    return d

def indexes():
    db.employees.create_index([('emp_code',ASCENDING)], unique=True, name='uq_employee_code')
    db.employees.create_index([('department',ASCENDING),('joined_on',ASCENDING),('emp_code',ASCENDING)], name='ix_employee_department_joined')
    db.employees.create_index([('joined_on',ASCENDING)], name='ix_employee_joined')
    db.employees.create_index([('department',ASCENDING),('emp_code',ASCENDING)], name='ix_employee_department_code')
    db.attendance_logs.create_index([('emp_code',ASCENDING),('date',ASCENDING)], unique=True, name='uq_attendance_employee_date')
    db.attendance_logs.create_index([('date',DESCENDING),('emp_code',ASCENDING)], name='ix_attendance_date_emp')
    db.attendance_logs.create_index([('emp_code',ASCENDING),('date',ASCENDING),('status',ASCENDING)], name='ix_attendance_emp_date_status')
    db.attendance_logs.create_index([('status',ASCENDING),('date',ASCENDING)], name='ix_attendance_status_date')
@app.on_event('startup')
def startup():
    # Index creation is idempotent; MongoDB readiness is separately exposed by /health.
    indexes()

class EmployeeIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    emp_code: str = Field(pattern=r'^EMP\d{4,6}$')
    name: str = Field(min_length=1,max_length=100)
    email: str = Field(max_length=120, pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    department: str = Field(min_length=1,max_length=50)
    shift_start: str = Field(default='09:30', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    shift_end: str = Field(default='18:30', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    joined_on: str
    @field_validator('joined_on')
    @classmethod
    def valid_joined(cls,v):
        try:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',v): raise ValueError()
            date.fromisoformat(v)
        except Exception: raise ValueError('joined_on must be YYYY-MM-DD')
        return v
class PunchInIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    emp_code: str
    punched_at: Optional[int] = Field(default=None, strict=True, ge=100_000_000_000, le=4_102_444_800_000)
    status: Literal['PRESENT','WFH','ON_DUTY']='PRESENT'
class PunchOutIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    emp_code: str
    punched_at: Optional[int] = Field(default=None, strict=True, ge=100_000_000_000, le=4_102_444_800_000)
class RegularizeIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status: Optional[Literal['PRESENT','ABSENT','LEAVE','WFH','ON_DUTY']]=None
    punch_in: Optional[int]=Field(default=None, strict=True, ge=100_000_000_000, le=4_102_444_800_000)
    punch_out: Optional[int]=Field(default=None, strict=True, ge=100_000_000_000, le=4_102_444_800_000)
    reason: str=Field(min_length=5,max_length=200)
    regularized_by: str=Field(min_length=1,max_length=50)

@app.get('/health')
def health():
    try: client.admin.command('ping'); return {'status':'ok'}
    except Exception: raise HTTPException(503,'MongoDB unavailable')
@app.post('/employees',status_code=201)
def create_employee(body:EmployeeIn):
    doc=body.model_dump(); doc['created_at']=now_utc()
    try: db.employees.insert_one(doc)
    except DuplicateKeyError: raise HTTPException(409,'emp_code already exists')
    doc.pop('_id',None)
    doc['created_at']=epoch_ms(doc['created_at'])
    return doc
@app.get('/employees')
def list_employees(department:Optional[str]=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):
    q={'department':department} if department is not None else {}
    total=db.employees.count_documents(q)
    items=list(db.employees.find(q,{'_id':0}).sort('emp_code',ASCENDING).skip((page-1)*page_size).limit(page_size))
    for x in items:
        if isinstance(x.get('created_at'),datetime): x['created_at']=epoch_ms(x['created_at'])
    return {'items':items,'total':total,'page':page,'page_size':page_size}
@app.post('/attendance/punch-in',status_code=201)
def punch_in(body:PunchInIn):
    emp=db.employees.find_one({'emp_code':body.emp_code})
    if not emp: raise HTTPException(404,'employee not found')
    try: ts=from_ms(body.punched_at) if body.punched_at is not None else now_utc()
    except ValueError as e: raise HTTPException(422,str(e))
    ts=ts.replace(microsecond=0); d=attendance_date(ts,emp)
    doc={'emp_code':body.emp_code,'date':d,'status':body.status,'punch_in':ts,'punch_out':None,'work_hours':None,'late_minutes':late_minutes(ts,emp),'overtime_minutes':0,'half_day':False,'history':[]}
    try: result=db.attendance_logs.insert_one(doc)
    except DuplicateKeyError: raise HTTPException(409,'already punched in for this date')
    doc['id']=str(result.inserted_id); return serialize_doc(doc)
@app.post('/attendance/punch-out')
def punch_out(body:PunchOutIn):
    emp=db.employees.find_one({'emp_code':body.emp_code})
    if not emp: raise HTTPException(404,'employee not found')
    try: ts=from_ms(body.punched_at) if body.punched_at is not None else now_utc()
    except ValueError as e: raise HTTPException(422,str(e))
    ts=ts.replace(microsecond=0)
    rec=db.attendance_logs.find_one({'emp_code':body.emp_code,'punch_in':{'$lte':ts}},sort=[('punch_in',DESCENDING)])
    if not rec: raise HTTPException(404,'no punch-in found')
    if rec.get('punch_out') is not None: raise HTTPException(409,'record already punched out')
    elapsed=(ts-dt_utc(rec['punch_in'])).total_seconds()
    if elapsed<=0 or elapsed>86400: raise HTTPException(422,'punch_out must be after punch_in and within 24 hours')
    vals=derived(rec['punch_in'],ts,emp)
    updated=db.attendance_logs.find_one_and_update({'_id':rec['_id'],'punch_out':None},{'$set':{'punch_out':ts,**vals}},return_document=ReturnDocument.AFTER)
    if updated is None: raise HTTPException(409,'record already punched out')
    return serialize_doc(updated)
@app.get('/attendance')
def list_attendance(emp_code:Optional[str]=None,date_from:Optional[str]=None,date_to:Optional[str]=None,status:Optional[str]=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):
    q={}
    if emp_code is not None:q['emp_code']=emp_code
    if status is not None:
        if status not in STATUSES: raise HTTPException(422,'invalid status')
        q['status']=status
    if date_from or date_to:
        q['date']={}
        if date_from:q['date']['$gte']=iso_date(date_from,'date_from')
        if date_to:q['date']['$lte']=iso_date(date_to,'date_to')
        if date_from and date_to and date_from>date_to:raise HTTPException(422,'date_from must be <= date_to')
    total=db.attendance_logs.count_documents(q)
    docs=list(db.attendance_logs.find(q).sort([('date',DESCENDING),('emp_code',ASCENDING)]).skip((page-1)*page_size).limit(page_size))
    return {'items':[serialize_doc(d) for d in docs],'total':total,'page':page,'page_size':page_size}
@app.patch('/attendance/{emp_code}/{date}')
def regularize(emp_code:str,date:str,body:RegularizeIn):
    date=iso_date(date)
    emp=db.employees.find_one({'emp_code':emp_code})
    if not emp:raise HTTPException(404,'employee not found')
    rec=db.attendance_logs.find_one({'emp_code':emp_code,'date':date})
    if not rec:raise HTTPException(404,'attendance record not found')
    old={k:rec.get(k) for k in ['status','punch_in','punch_out','work_hours','late_minutes','overtime_minutes','half_day']}
    status=body.status if body.status is not None else rec['status']
    if status in ('ABSENT','LEAVE'):
        if body.punch_in is not None or body.punch_out is not None:raise HTTPException(422,'ABSENT/LEAVE cannot have punch times')
        pin=pout=None
    else:
        if body.punch_in is not None:
            try:pin=from_ms(body.punch_in)
            except ValueError as e:raise HTTPException(422,str(e))
        else:pin=rec.get('punch_in')
        if body.punch_out is not None:
            try:pout=from_ms(body.punch_out)
            except ValueError as e:raise HTTPException(422,str(e))
        else:pout=rec.get('punch_out')
        if pin is None:raise HTTPException(422,'presence status requires punch_in')
        if attendance_date(pin,emp)!=date:raise HTTPException(422,'punch_in must belong to record attendance date')
        if pout is not None and ((pout-pin).total_seconds()<=0 or (pout-pin).total_seconds()>86400):raise HTTPException(422,'punch_out must be after punch_in and within 24 hours')
    vals=derived(pin,pout,emp) if status in PRESENT else {'late_minutes':0,'work_hours':None,'overtime_minutes':0,'half_day':False}
    new={'status':status,'punch_in':pin,'punch_out':pout,**vals}
    changes={}
    for k,v in new.items():
        a=old.get(k)
        if isinstance(a,datetime): a=dt_utc(a)
        if isinstance(v,datetime): v=dt_utc(v)
        if a!=v: changes[k]={'from':old.get(k),'to':v}
    if not changes:raise HTTPException(422,'request does not change the record')
    hist={'at':now_utc(),'by':body.regularized_by,'reason':body.reason,'changes':changes}
    # Compare-and-swap protects history from lost updates; a concurrent loser receives 409.
    query={'_id':rec['_id']}
    for k in old: query[k]=rec.get(k)
    updated=db.attendance_logs.find_one_and_update(query,{'$set':new,'$push':{'history':hist}},return_document=ReturnDocument.AFTER)
    if updated is None:raise HTTPException(409,'record changed concurrently; retry')
    return serialize_doc(updated)

# Aggregation expressions shared by analytics.
def attendance_match(start,end,emp_code=None):
    q={'date':{'$gte':start,'$lte':end}}
    if emp_code:q['emp_code']=emp_code
    return q
def round_expr(expr,places=2):
    # All reported quantities here are non-negative; this implements half-up, unlike $round's ties-to-even.
    scale=10**places
    return {'$divide':[{'$floor':{'$add':[{'$multiply':[expr,scale]},0.5]}},scale]}

def employee_monthly_pipeline(emp_code,month):
    start,last,next_month=month_bounds(month)
    return [
      {'$match':{'emp_code':emp_code,'date':{'$gte':start,'$lt':next_month}}},
      {'$set':{'_day':{'$dateFromString':{'dateString':'$date'}},'_present':{'$cond':[{'$in':['$status',PRESENT]},{'$cond':[{'$eq':['$half_day',True]},0.5,1]},0]} }},
      {'$group':{'_id':None,'present_days':{'$sum':{'$cond':[{'$and':[{'$lt':[{'$dayOfWeek':'$_day'},7]},{'$gt':[{'$dayOfWeek':'$_day'},1]}]},'$_present',0]}},'leave_days':{'$sum':{'$cond':[{'$eq':['$status','LEAVE']},1,0]}},'late_count':{'$sum':{'$cond':[{'$gt':[{'$ifNull':['$late_minutes',0]},0]},1,0]}}}}
    ]
@app.get('/analytics/employees/{emp_code}/monthly')
def employee_monthly(emp_code:str,month:str=Query(...,pattern=r'^\d{4}-(0[1-9]|1[0-2])$')):
    emp=db.employees.find_one({'emp_code':emp_code})
    if not emp:raise HTTPException(404,'employee not found')
    start,last,nxt=month_bounds(month); working_start=max(start,emp['joined_on'])
    working=day_count_working(working_start,last) if working_start<=last else 0
    got=list(db.attendance_logs.aggregate(employee_monthly_pipeline(emp_code,month)))
    r=got[0] if got else {}
    present=money(r.get('present_days',0)); pct=money(Decimal(str(present))/Decimal(working)*100,4) if working else None
    return {'emp_code':emp_code,'month':month,'working_days':working,'present_days':present,'leave_days':r.get('leave_days',0),'late_count':r.get('late_count',0),'attendance_pct':pct}

def department_summary_pipeline(start,nxt,department=None):
    emp_match={'joined_on':{'$lt':nxt}}
    if department is not None:emp_match['department']=department
    return [
      {'$match':emp_match},
      {'$lookup':{'from':'attendance_logs','let':{'code':'$emp_code'},'pipeline':[{'$match':{'$expr':{'$and':[{'$eq':['$emp_code','$$code']},{'$gte':['$date',start]},{'$lt':['$date',nxt]}]}}}], 'as':'logs'}},
      {'$unwind':{'path':'$logs','preserveNullAndEmptyArrays':True}},
      {'$set':{'_day':{'$cond':[{'$ne':[{'$ifNull':['$logs.date',None]},None]},{'$dateFromString':{'dateString':'$logs.date'}},None]},'_present':{'$cond':[{'$in':['$logs.status',PRESENT]},{'$cond':[{'$eq':['$logs.half_day',True]},0.5,1]},0]} }},
      {'$group':{'_id':'$department','_headcount':{'$addToSet':'$emp_code'},'present_days':{'$sum':{'$cond':[{'$and':[{'$ne':['$_day',None]},{'$lt':[{'$dayOfWeek':'$_day'},7]},{'$gt':[{'$dayOfWeek':'$_day'},1]}]},'$_present',0]}},'hours':{'$push':{'$cond':[{'$and':[{'$in':['$logs.status',PRESENT]},{'$ne':[{'$ifNull':['$logs.work_hours',None]},None]}]},'$logs.work_hours',None]}},'late_count':{'$sum':{'$cond':[{'$gt':[{'$ifNull':['$logs.late_minutes',0]},0]},1,0]}},'total_late_minutes':{'$sum':{'$ifNull':['$logs.late_minutes',0]}},'leave_count':{'$sum':{'$cond':[{'$eq':['$logs.status','LEAVE']},1,0]}},'on_duty_count':{'$sum':{'$cond':[{'$eq':['$logs.status','ON_DUTY']},1,0]}}}},
      {'$set':{'headcount':{'$size':'$_headcount'},'_hours':{'$filter':{'input':'$hours','as':'h','cond':{'$ne':['$$h',None]}}}}},
      {'$set':{'avg_work_hours':{'$cond':[{'$gt':[{'$size':'$_hours'},0]},round_expr({'$avg':'$_hours'},2),None]},'present_days':round_expr('$present_days',2)}},
      {'$match':{'headcount':{'$gt':0}}},{'$sort':{'_id':1}},
      {'$project':{'_id':0,'department':'$_id','headcount':1,'present_days':1,'avg_work_hours':1,'late_count':1,'total_late_minutes':1,'leave_count':1,'on_duty_count':1}}
    ]
@app.get('/analytics/departments/summary')
def department_summary(month:str=Query(...,pattern=r'^\d{4}-(0[1-9]|1[0-2])$'),department:Optional[str]=None):
    start,last,nxt=month_bounds(month)
    return list(db.employees.aggregate(department_summary_pipeline(start,nxt,department),allowDiskUse=True))

def leaderboard_pipeline(start,nxt,department=None,limit=10):
    p=[{'$match':{'date':{'$gte':start,'$lt':nxt},'late_minutes':{'$gt':0}}},{'$group':{'_id':'$emp_code','total_late_minutes':{'$sum':'$late_minutes'}}},{'$lookup':{'from':'employees','localField':'_id','foreignField':'emp_code','as':'employee'}},{'$unwind':'$employee'}]
    if department is not None:p.append({'$match':{'employee.department':department}})
    p += [{'$setWindowFields':{'sortBy':{'total_late_minutes':-1},'output':{'rank':{'$rank':{}}}}},{'$match':{'rank':{'$lte':limit}}},{'$sort':{'total_late_minutes':-1,'_id':1}},{'$project':{'_id':0,'emp_code':'$_id','name':'$employee.name','department':'$employee.department','total_late_minutes':1,'rank':1}}]
    return p
@app.get('/analytics/leaderboard/late')
def late_leaderboard(month:str=Query(...,pattern=r'^\d{4}-(0[1-9]|1[0-2])$'),limit:int=Query(10,ge=1,le=50),department:Optional[str]=None):
    start,last,nxt=month_bounds(month)
    return list(db.attendance_logs.aggregate(leaderboard_pipeline(start,nxt,department,limit),allowDiskUse=True))

# Trend pipeline starts from employees so even an entirely empty day range gets a date spine.
def trend_pipeline(department, start, end):
    startdt=datetime.combine(date.fromisoformat(start),time.min,UTC); enddt=datetime.combine(date.fromisoformat(end),time.min,UTC)
    days=(date.fromisoformat(end)-date.fromisoformat(start)).days+1
    return [
      {'$match':{'department':department}},
      {'$group':{'_id':None,'codes':{'$addToSet':'$emp_code'},'employees':{'$push':{'emp_code':'$emp_code','joined_on':'$joined_on'}}}},
      {'$set':{'_dates':{'$map':{'input':{'$range':[0,days]},'as':'i','in':{'$dateAdd':{'startDate':startdt,'unit':'day','amount':'$$i'}}}}}},
      {'$unwind':'$_dates'},
      {'$set':{'_date':{'$dateToString':{'date':'$_dates','format':'%Y-%m-%d','timezone':'UTC'}},'is_working_day':{'$and':[{'$gt':[{'$dayOfWeek':'$_dates'},1]},{'$lt':[{'$dayOfWeek':'$_dates'},7]}]},'headcount':{'$size':{'$filter':{'input':'$employees','as':'e','cond':{'$lte':['$$e.joined_on',{'$dateToString':{'date':'$_dates','format':'%Y-%m-%d','timezone':'UTC'}}]}}}}}},
      {'$lookup':{'from':'attendance_logs','let':{'d':'$_date','codes':'$codes'},'pipeline':[{'$match':{'$expr':{'$and':[{'$eq':['$date','$$d']},{'$in':['$emp_code','$$codes']}]}}},{'$group':{'_id':None,'present_count':{'$sum':{'$cond':[{'$in':['$status',PRESENT]},{'$cond':[{'$eq':['$half_day',True]},0.5,1]},0]}},'late_count':{'$sum':{'$cond':[{'$gt':[{'$ifNull':['$late_minutes',0]},0]},1,0]}}}}], 'as':'daily'}},
      {'$set':{'_d':{'$arrayElemAt':['$daily',0]},'present_count':{'$ifNull':[{'$arrayElemAt':['$daily.present_count',0]},0]},'late_count':{'$ifNull':[{'$arrayElemAt':['$daily.late_count',0]},0]}}},
      {'$set':{'attendance_rate':{'$cond':[{'$and':['$is_working_day',{'$gt':['$headcount',0]}]},round_expr({'$divide':['$present_count','$headcount']},4),None]}}},
      {'$setWindowFields':{'sortBy':{'_dates':1},'output':{'moving_avg_7d':{'$avg':'$attendance_rate','window':{'documents':[-6,0]}}}}},
      {'$sort':{'_dates':1}},
      {'$project':{'_id':0,'date':'$_date','is_working_day':1,'headcount':1,'present_count':round_expr('$present_count',2),'late_count':1,'attendance_rate':1,'moving_avg_7d':{'$cond':[{'$eq':[{'$type':'$moving_avg_7d'},'missing']},None,round_expr('$moving_avg_7d',4)]}}}
    ]
@app.get('/analytics/departments/{department}/trend')
def department_trend(department:str,from_:str=Query(...,alias='from'),to:str=Query(...)):
    start=iso_date(from_,'from'); end=iso_date(to,'to')
    if end<start:raise HTTPException(422,'to must be on or after from')
    if (date.fromisoformat(end)-date.fromisoformat(start)).days+1>92:raise HTTPException(422,'range cannot exceed 92 days')
    if not db.employees.find_one({'department':department}):raise HTTPException(404,'department not found')
    return list(db.employees.aggregate(trend_pipeline(department,start,end),allowDiskUse=True))

@app.get('/admin/explain/{endpoint}')
def explain(endpoint:str,emp_code:Optional[str]=None,month:Optional[str]=None,department:Optional[str]=None,limit:int=Query(10,ge=1,le=50),date_from:Optional[str]=None,date_to:Optional[str]=None,status:Optional[str]=None,from_:Optional[str]=Query(None,alias='from'),to:Optional[str]=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):
    valid=['attendance_list','employee_monthly','department_summary','late_leaderboard','department_trend']
    if endpoint not in valid:raise HTTPException(422,'unknown endpoint')
    if endpoint=='attendance_list':
        q={}
        if emp_code:q['emp_code']=emp_code
        if status:q['status']=status
        if date_from or date_to:
            q['date']={}
            if date_from:q['date']['$gte']=iso_date(date_from,'date_from')
            if date_to:q['date']['$lte']=iso_date(date_to,'date_to')
        exp=db.command('explain',{'find':'attendance_logs','filter':q,'sort':{'date':-1,'emp_code':1},'skip':(page-1)*page_size,'limit':page_size},verbosity='executionStats'); coll='attendance_logs'
    elif endpoint=='employee_monthly':
        if not emp_code or not month:raise HTTPException(422,'emp_code and month are required')
        start,last,nxt=month_bounds(month); pipeline=employee_monthly_pipeline(emp_code,month)
        exp=db.command('explain',{'aggregate':'attendance_logs','pipeline':pipeline,'cursor':{}},verbosity='executionStats'); coll='attendance_logs'
    elif endpoint=='department_summary':
        if not month:raise HTTPException(422,'month is required')
        start,last,nxt=month_bounds(month); pipeline=department_summary_pipeline(start,nxt,department)
        exp=db.command('explain',{'aggregate':'employees','pipeline':pipeline,'cursor':{},'allowDiskUse':True},verbosity='executionStats'); coll='employees'
    elif endpoint=='late_leaderboard':
        if not month:raise HTTPException(422,'month is required')
        start,last,nxt=month_bounds(month); pipeline=leaderboard_pipeline(start,nxt,department,limit)
        exp=db.command('explain',{'aggregate':'attendance_logs','pipeline':pipeline,'cursor':{},'allowDiskUse':True},verbosity='executionStats'); coll='attendance_logs'
    else:
        if not department or not from_ or not to:raise HTTPException(422,'department, from and to are required')
        start=iso_date(from_,'from'); end=iso_date(to,'to')
        if end<start or (date.fromisoformat(end)-date.fromisoformat(start)).days+1>92:raise HTTPException(422,'invalid date range')
        pipeline=trend_pipeline(department,start,end)
        exp=db.command('explain',{'aggregate':'employees','pipeline':pipeline,'cursor':{},'allowDiskUse':True},verbosity='executionStats'); coll='employees'
    return {'endpoint':endpoint,'collection':coll,'explain':exp}
