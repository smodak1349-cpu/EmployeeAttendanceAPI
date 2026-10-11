from datetime import datetime, timezone
from pymongo import MongoClient

MONGO_URI = "mongodb+srv://sumit_admin:sumit123@cluster0.ajfyi1z.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client["attendance_db"]

# Purana sara data clear karein
db.employees.delete_many({})
db.attendance_logs.delete_many({})

# Fresh Sample Employees
employees = [
    {
        "emp_code": "EMP0001",
        "name": "Asha Rao",
        "email": "asha@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-05",
        "created_at": datetime.now(timezone.utc)
    },
    {
        "emp_code": "EMP0002",
        "name": "Vikram Shah",
        "email": "vikram@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-07-13",
        "created_at": datetime.now(timezone.utc)
    },
    {
        "emp_code": "EMP0003",
        "name": "Neha Iyer",
        "email": "neha@example.com",
        "department": "Sales",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-02-01",
        "created_at": datetime.now(timezone.utc)
    }
]

db.employees.insert_many(employees)
print("Database successfully reset and seeded with fresh data!")