# REVIEW.md

## Issues Found in the Starter Code

| # | Function / location | Issue found | Test case / impact | Fix applied |
| ---: | :--- | :--- | :--- | :--- |
| 1 | `compute_late_minutes` | The grace-period calculation may not handle seconds at the 10-minute boundary correctly. | Test punch-ins at 09:40:00 and 09:40:01 for a 09:30 shift. | Compare elapsed seconds with the grace-period boundary before calculating late minutes. |
| 2 | `compute_late_minutes` | Overnight shifts may be associated with the wrong attendance date. | Test a 22:00–06:00 shift with a punch-in after midnight. | Handle the shift date and start time using IST and the overnight-shift rules. |
| 3 | `compute_work_hours` | Floating-point rounding may not match the required two-decimal rounding behavior. | Test durations close to a rounding boundary. | Calculate duration from elapsed seconds and apply an explicit rounding rule. |
| 4 | `compute_overtime` | The shift end may be calculated on the wrong date for overnight shifts. | Test a 22:00–06:00 shift with a punch-out after 06:00 the following day. | Calculate the shift end on the correct date and apply the specified overtime threshold. |
| 5 | MongoDB client setup | Datetime handling may not be consistently timezone-aware. | Read stored timestamps and compare them with the API timestamp format. | Use timezone-aware datetime handling and consistent conversions at the API boundary. |
| 6 | `health` | The endpoint may report success when MongoDB is unavailable. | Stop MongoDB and request `/health`. | Check database connectivity and return an appropriate error status when the database is unavailable. |
| 7 | `create_employee` | Application-side duplicate checking is not sufficient for concurrent requests. | Send two simultaneous requests with the same employee code. | Enforce uniqueness with a database index and handle duplicate-key errors with HTTP 409. |
| 8 | `create_employee` | The creation timestamp may not follow the required timezone and response format. | Inspect `created_at` and compare its representation with the API contract. | Store timestamps consistently in UTC and serialize them as required by the contract. |
| 9 | Employee request validation | Employee fields may accept invalid formats or values. | Submit an invalid employee code, shift time, or email address. | Add validation for the formats, lengths, and ranges required by the contract. |
| 10 | `list_employees` | The pagination offset may skip the first page. | Request page 1 with a page size of 20. | Calculate the offset using `(page - 1) * page_size`. |
| 11 | `list_employees` | The total count may not apply the same filter as the employee query. | Filter employees by department and compare the returned total. | Use the same filter for both the query and `count_documents`. |
| 12 | `list_employees` | Invalid pagination values or inconsistent sorting may produce incorrect results. | Request page 0, a negative page size, or records with identical sort values. | Validate pagination inputs and use deterministic sorting. |
| 13 | `punch_in` | An unknown employee may not be handled before accessing shift details. | Punch in using an employee code that does not exist. | Return HTTP 404 when the employee is not found. |
| 14 | `punch_in` | Timestamp conversion may depend on the machine's local timezone or incorrect precision. | Test timestamps around midnight UTC and IST. | Normalize timestamps consistently and follow the contract's timezone and precision rules. |
| 15 | `punch_in` | Concurrent requests may create duplicate attendance records. | Send simultaneous punch-in requests for the same employee and date. | Add a unique compound index on `(emp_code, date)` and handle duplicate-key errors. |
| 16 | `punch_in` | The endpoint may accept attendance statuses that are not valid for punch-in. | Submit a status such as `ABSENT` to the punch-in endpoint. | Validate the status against the values permitted by the API contract. |
| 17 | `list_attendance` | Loading all matching records into Python before pagination can waste memory. | Query a large attendance dataset. | Apply filtering, sorting, skipping, and limiting directly in MongoDB. |
| 18 | `list_attendance` | Invalid date formats or reversed date ranges may not be rejected. | Submit malformed dates or a start date later than the end date. | Validate the date inputs and reject invalid ranges with HTTP 422. |
| 19 | `list_attendance` | Invalid pagination or unstable sorting can lead to inconsistent pages. | Request invalid page values or records with identical dates. | Validate pagination inputs and add a stable secondary sort key. |
| 20 | Missing punch-out endpoint | The starter code does not provide the required punch-out operation. | Call `POST /attendance/punch-out`. | Implement punch-out validation, conditional updates, and derived-field calculations. |
| 21 | Missing regularization endpoint | Manual attendance corrections and their audit history are not implemented. | Call `PATCH /attendance/{emp_code}/{date}`. | Validate corrections and preserve the required history of changes. |
| 22 | Missing employee monthly analytics | Monthly analytics for an individual employee are unavailable. | Call `GET /analytics/employees/{emp_code}/monthly`. | Implement the required MongoDB aggregation pipeline. |
| 23 | Missing department summary | Department-level attendance summaries are unavailable. | Call `GET /analytics/departments/summary`. | Implement the aggregation while preserving headcount for employees without attendance records. |
| 24 | Missing late leaderboard | The API cannot return the required late-arrival rankings. | Call `GET /analytics/leaderboard/late`. | Implement ranking and tie handling according to the API contract. |
| 25 | Missing department trend | Department attendance trends are unavailable. | Call `GET /analytics/departments/{department}/trend`. | Implement the required date-range aggregation. |
| 26 | Missing explain endpoint | Query execution plans are not available through the API. | Call `GET /admin/explain/{endpoint}`. | Implement query explanations with execution statistics for supported endpoints. |
| 27 | Application startup and indexes | Required indexes for uniqueness and query performance may be missing. | Inspect database indexes or examine query execution statistics. | Create the required indexes during application startup. |
| 28 | Request and response handling | Timestamp formats, validation, or response fields may not consistently follow the API contract. | Submit invalid timestamps or inspect response field types. | Validate inputs and serialize responses according to the documented contract. |

## Items Checked but Not Considered Issues

| Item | Reason |
| :--- | :--- |
| `MONGO_URI` and `MONGO_DB` environment variables | Using environment variables for database configuration supports both local development and hosted databases. |
| Loading a local `.env` file | This is suitable for local development as long as credentials are not committed to GitHub. |
| `emp_code` as the employee identifier | The API contract uses the employee code as the business identifier, while MongoDB `_id` can remain an internal identifier. |
| An initially empty attendance history | A new attendance record with no manual corrections should have an empty history array. |
| Default shift times | Default values are acceptable when they match the supplied data model and API contract. |
| Attendance dates stored as `YYYY-MM-DD` strings | This is appropriate when the contract defines attendance dates as calendar dates in that format. |
| MongoDB aggregation pipelines for analytics | Aggregation pipelines allow calculations to run in the database and reduce unnecessary data transfer to the application. |

## Testing Notes

The issues listed above should be checked against the original starter code and the final implementation. The fixes described in the table must match the actual submitted code.

Database-dependent behavior, aggregation results, concurrent requests, and query execution plans still need integration testing against a reachable MongoDB instance before they can be considered verified.
