import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pymongo import MongoClient

MONGO_URI = "mongodb+srv://sumit_admin:sumit123@cluster0.ajfyi1z.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client["attendance_db"]

IST = timezone(timedelta(hours=5, minutes=30))
app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    if punch_in.tzinfo is None:
        punch_in = punch_in.replace(tzinfo=IST)
    h, m = map(int, shift_start.split(":"))
    start = punch_in.replace(hour=h, minute=m, second=0, microsecond=0)
    minutes = int((punch_in - start).total_seconds() / 60)
    return minutes if minutes > 10 else 0

def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    if punch_in.tzinfo is None:
        punch_in = punch_in.replace(tzinfo=IST)
    if punch_out.tzinfo is None:
        punch_out = punch_out.replace(tzinfo=IST)
    return round((punch_out - punch_in).total_seconds() / 3600, 2)

def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    if punch_out.tzinfo is None:
        punch_out = punch_out.replace(tzinfo=IST)
    h, m = map(int, shift_end.split(":"))
    dt_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    end = datetime(dt_obj.year, dt_obj.month, dt_obj.day, h, m, tzinfo=IST)
    return max(0, int((punch_out - end).total_seconds() / 60))

class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

class PunchOutIn(BaseModel):
    emp_code: str
    punched_out_at: Optional[int] = None

@app.get("/")
def home():
    try:
        client.admin.command('ping')
        return {"message": "Database successfully connected with MongoDB Atlas!"}
    except Exception as e:
        return {"message": f"Connection failed: {e}"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc

@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = 1, page_size: int = 20):
    q = {}
    if department:
        q["department"] = department
    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)
    items = list(db.employees.find(q, {"_id": 0}).skip(skip).limit(page_size))
    return {"items": items, "total": total, "page": page, "page_size": page_size}

@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "Employee not found")
    ts = datetime.fromtimestamp(body.punched_at / 1000, tz=IST) if body.punched_at else datetime.now(IST)
    d = ts.date().isoformat()
    
    if db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d}):
        raise HTTPException(409, "already punched in for this date")
    
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"]),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    res = db.attendance_logs.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc

@app.post("/attendance/punch-out", status_code=200)
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "Employee not found")
    ts = datetime.fromtimestamp(body.punched_out_at / 1000, tz=IST) if body.punched_out_at else datetime.now(IST)
    d = ts.date().isoformat()
    
    log = db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d})
    if not log or not log.get("punch_in"):
        raise HTTPException(400, "No active punch-in found for today")
    if log.get("punch_out"):
        raise HTTPException(409, "already punched out for this date")
        
    p_in = log["punch_in"]
    wh = compute_work_hours(p_in, ts)
    ot = compute_overtime(ts, emp["shift_end"], d)
    half = True if wh < 4.0 else False

    db.attendance_logs.update_one(
        {"_id": log["_id"]},
        {"$set": {"punch_out": ts, "work_hours": wh, "overtime_minutes": ot, "half_day": half}}
    )
    
    updated_log = db.attendance_logs.find_one({"_id": log["_id"]})
    updated_log["id"] = str(updated_log.pop("_id"))
    return updated_log

@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
        
    docs = list(db.attendance_logs.find(q))
    docs.sort(key=lambda d: d["date"], reverse=True)
    total = len(docs)
    page_docs = docs[(page - 1) * page_size : page * page_size]
    for d in page_docs:
        d["id"] = str(d.pop("_id"))
    return {"items": page_docs, "total": total, "page": page, "page_size": page_size}

@app.get("/analytics/departments/summary")
def department_summary(date: Optional[str] = None):
    target_date = date if date else datetime.now(IST).date().isoformat()
    employees = list(db.employees.find({}, {"_id": 0}))
    depts = {}
    
    for emp in employees:
        dept = emp["department"]
        if dept not in depts:
            depts[dept] = {"department": dept, "headcount": 0, "present": 0, "absent": 0, "wfh": 0, "leave": 0}
        depts[dept]["headcount"] += 1
        
    logs = list(db.attendance_logs.find({"date": target_date}))
    log_map = {l["emp_code"]: l for l in logs}
    
    for emp in employees:
        dept = emp["department"]
        l = log_map.get(emp["emp_code"])
        if l:
            st = l.get("status", "").lower()
            if st in depts[dept]:
                depts[dept][st] += 1
        else:
            depts[dept]["absent"] += 1
            
    return {"date": target_date, "departments": list(depts.values())}

@app.get("/analytics/leaderboard/late")
def late_leaderboard(month: str, limit: int = 10):
    pipeline = [
        {"$match": {"date": {"$regex": f"^{month}"}, "late_minutes": {"$gt": 0}}},
        {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": "$late_minutes"}, "late_days": {"$sum": 1}}},
        {"$sort": {"total_late_minutes": -1}},
        {"$limit": limit}
    ]
    results = list(db.attendance_logs.aggregate(pipeline))
    items = []
    for r in results:
        emp = db.employees.find_one({"emp_code": r["_id"]}, {"_id": 0})
        items.append({
            "emp_code": r["_id"],
            "name": emp["name"] if emp else "Unknown",
            "department": emp["department"] if emp else "Unknown",
            "total_late_minutes": r["total_late_minutes"],
            "late_days": r["late_days"]
        })
    return {"month": month, "leaderboard": items}