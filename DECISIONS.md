# DECISIONS.md

## 1. Indexes
I created a unique index on `emp_code` to prevent duplicate employees and a unique compound index on `emp_code` and `date` to prevent duplicate attendance records. I also considered adding indexes to every analytics field, but rejected that because unnecessary indexes increase storage and slow down writes. Additional indexes should be based on actual query performance.

## 2. Punch-in race
If two identical punch-in requests arrive simultaneously, both may initially check for an existing attendance record. The unique compound index ensures that only one record can be inserted. The other request encounters a duplicate-key error, which the API should handle with an appropriate conflict response instead of creating a duplicate record.

## 3. Ties
The leaderboard uses late minutes to rank employees. If employees are tied at the cutoff, the result depends on whether the query returns exactly `limit` records or includes all employees tied at that position. A stable secondary sort makes the output deterministic.

## 4. Headcount
The department summary starts from employee records and includes attendance information through a lookup or equivalent aggregation. This ensures employees with no attendance records are still counted.

## 5. One improvement
For 100 times more data, I would review query execution plans, add indexes based on measured workloads, and optimize aggregation pipelines before increasing infrastructure capacity.
