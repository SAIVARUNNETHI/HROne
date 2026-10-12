# HROne

Employee Attendance & Analytics API

This project implements an Employee Attendance and Analytics API using Python, FastAPI, and MongoDB.

Features:
- Employee creation and listing with pagination.
- Attendance punch-in and punch-out.
- Attendance record retrieval and manual corrections with audit history.
- Monthly employee attendance analytics.
- Department attendance summaries and trends.
- Late-arrival leaderboard.
- MongoDB query execution-plan explanations.

Requirements:
- Python 3.11+
- MongoDB
- Dependencies listed in requirements.txt.

Setup:

Install the dependencies:

    pip install -r requirements.txt

Configure the MongoDB connection using the MONGO_URI and MONGO_DB environment variables.

Run the application from the project root:

    uvicorn app.main:app --port 8000

API Documentation:

After starting the application, access the interactive API documentation at:

http://127.0.0.1:8000/docs

Configuration and Security:

MongoDB connection settings should be configured through environment variables. Do not commit credentials, secrets, or .env files to the public repository.

Testing:

Test the API endpoints with a reachable MongoDB instance, including attendance operations, manual corrections, and analytics queries.
