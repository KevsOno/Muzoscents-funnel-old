from datetime import datetime, timezone, date
from typing import Optional, Tuple, List, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from deps import (
    logger, get_supabase, run_sync_db_call,
    get_client_ip, rate_limit,
    require_role, require_feature,
    resolve_request_branch, resolve_request_branch_for_write,
    get_visible_user_ids,
)

hr_router = APIRouter(
    prefix="/hr",
    tags=["Human Resources"],
    dependencies=[Depends(require_feature("hr_module"))],
)

# ===================== HR MODULE MODELS =====================
class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None

class DepartmentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None

class EmployeeCreate(BaseModel):
    user_id: Optional[str] = None
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    department_id: Optional[int] = None
    position: Optional[str] = None
    hire_date: date
    date_of_birth: Optional[date] = None
    salary: float = 0.0
    status: str = "active"

class EmployeeUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    department_id: Optional[int] = None
    position: Optional[str] = None
    hire_date: Optional[date] = None
    date_of_birth: Optional[date] = None
    salary: Optional[float] = None
    status: Optional[str] = None

class AttendanceClockIn(BaseModel):
    employee_id: int
    clock_in: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AttendanceClockOut(BaseModel):
    employee_id: int
    clock_out: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class LeaveRequestCreate(BaseModel):
    employee_id: int
    leave_type: str = Field(..., pattern="^(annual|sick|personal)$")
    start_date: date
    end_date: date
    reason: Optional[str] = None

class LeaveRequestUpdate(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected)$")
    approved_by: Optional[str] = None
    notes: Optional[str] = None

class PayrollGenerate(BaseModel):
    month: int = Field(..., ge=1, le=12)
    year: int

# ===================== HR HELPERS =====================
async def get_employee_by_user_id(user_id: str, org_id: str) -> Optional[Dict]:
    client = get_supabase()
    result = await run_sync_db_call(
        client.table("hr_employees")
        .select("*")
        .eq("user_id", user_id)
        .eq("org_id", org_id)
        .limit(1)  # FIXED: was .limit(1)
        .execute
    )
    return result.data[0] if result.data else None

async def get_employee_by_id(employee_id: int, org_id: str) -> Optional[Dict]:
    client = get_supabase()
    result = await run_sync_db_call(
        client.table("hr_employees")
        .select("*")
        .eq("id", employee_id)
        .eq("org_id", org_id)
        .limit(1)  # FIXED: was .limit(1)
        .execute
    )
    return result.data[0] if result.data else None

# ===================== HR ROUTER (Wave 3: feature-gated) =====================
# ===================== HR ENDPOINTS =====================
@hr_router.get("/departments")
async def list_departments(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    result = await run_sync_db_call(
        client.table("hr_departments")
        .select("*")
        .eq("org_id", org_id)
        .order("name")
        .execute
    )
    return {"departments": result.data}

@hr_router.post("/departments")
async def create_department(
    request: Request,
    dept: DepartmentCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    data = dept.dict()
    data["org_id"] = org_id
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    result = await run_sync_db_call(client.table("hr_departments").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create department")
    return result.data[0]

@hr_router.put("/departments/{dept_id}")
async def update_department(
    request: Request,
    dept_id: int,
    dept: DepartmentUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    existing = await run_sync_db_call(
        client.table("hr_departments")
        .select("id")
        .eq("id", dept_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Department not found")
    update_data = {k: v for k, v in dept.dict().items() if v is not None}
    result = await run_sync_db_call(
        client.table("hr_departments")
        .update(update_data)
        .eq("id", dept_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update department")
    return result.data[0]

@hr_router.delete("/departments/{dept_id}")
async def delete_department(
    request: Request,
    dept_id: int,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    emp_check = await run_sync_db_call(
        client.table("hr_employees")
        .select("id")
        .eq("department_id", dept_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute
    )
    if emp_check.data:
        raise HTTPException(status_code=400, detail="Cannot delete department with employees assigned")
    result = await run_sync_db_call(
        client.table("hr_departments")
        .delete()
        .eq("id", dept_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Department not found")
    return {"message": "Department deleted"}

@hr_router.get("/employees")
async def list_employees(
    request: Request,
    department_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "finance"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()

    selected_branch = await resolve_request_branch(request, user_id, org_id, role)
    visible_user_ids = await get_visible_user_ids(user_id, org_id, role)

    query = client.table("hr_employees").select("*").eq("org_id", org_id)
    if department_id:
        query = query.eq("department_id", department_id)
    if status:
        query = query.eq("status", status)
    if selected_branch:
        query = query.eq("branch_id", selected_branch)

    result = await run_sync_db_call(query.order("last_name").range(offset, offset + limit - 1).execute)
    rows = result.data or []

    # Owners (visible_user_ids is None) see everything. Everyone else sees
    # only HR records whose linked user_id is in their branch-sharing set,
    # plus unlinked records (no user_id → nothing to gate on yet).
    if visible_user_ids is not None:
        rows = [
            r for r in rows
            if not r.get("user_id") or r["user_id"] in visible_user_ids
        ]

    return {"employees": rows, "total": len(rows)}

@hr_router.post("/employees")
async def create_employee(
    request: Request,
    emp: EmployeeCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()
    if emp.user_id:
        member_check = await run_sync_db_call(
            client.table("org_members")
            .select("user_id")
            .eq("user_id", emp.user_id)
            .eq("org_id", org_id)
            .limit(1)
            .execute
        )
        if not member_check.data:
            raise HTTPException(status_code=400, detail="User is not a member of this organisation")
    email_check = await run_sync_db_call(
        client.table("hr_employees")
        .select("id")
        .eq("email", emp.email)
        .eq("org_id", org_id)
        .limit(1)
        .execute
    )
    if email_check.data:
        raise HTTPException(status_code=400, detail="Employee with this email already exists")

    data = emp.dict()
    if data.get("hire_date"):
        data["hire_date"] = data["hire_date"].isoformat()
    if data.get("date_of_birth"):
        data["date_of_birth"] = data["date_of_birth"].isoformat()
    data["org_id"] = org_id
    data["branch_id"] = await resolve_request_branch_for_write(request, user_id, org_id, role)
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await run_sync_db_call(client.table("hr_employees").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create employee")
    return result.data[0]

@hr_router.get("/employees/{employee_id}")
async def get_employee(
    request: Request,
    employee_id: int,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "finance", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()
    if role == "employee":
        emp = await get_employee_by_user_id(user_id, org_id)
        if not emp or emp["id"] != employee_id:
            raise HTTPException(status_code=403, detail="Not authorised to view this employee")
    result = await run_sync_db_call(
        client.table("hr_employees")
        .select("*")
        .eq("id", employee_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Employee not found")
    return result.data[0]

@hr_router.put("/employees/{employee_id}")
async def update_employee(
    request: Request,
    employee_id: int,
    emp: EmployeeUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    existing = await get_employee_by_id(employee_id, org_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Employee not found")
    update_data = {k: v for k, v in emp.dict().items() if v is not None}
    if update_data.get("hire_date"):
        update_data["hire_date"] = update_data["hire_date"].isoformat()
    if update_data.get("date_of_birth"):
        update_data["date_of_birth"] = update_data["date_of_birth"].isoformat()
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await run_sync_db_call(
        client.table("hr_employees")
        .update(update_data)
        .eq("id", employee_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update employee")
    return result.data[0]

@hr_router.delete("/employees/{employee_id}")
async def delete_employee(
    request: Request,
    employee_id: int,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    existing = await get_employee_by_id(employee_id, org_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Employee not found")
    result = await run_sync_db_call(
        client.table("hr_employees")
        .delete()
        .eq("id", employee_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to delete employee")
    return {"message": "Employee deleted"}

@hr_router.get("/me")
async def get_my_employee_profile(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["employee"]))
):
    user_id, org_id, _ = user_data
    emp = await get_employee_by_user_id(user_id, org_id)
    if not emp:
        raise HTTPException(status_code=404, detail="No employee profile found for this user")
    return emp

@hr_router.post("/attendance/clock-in")
async def clock_in(
    request: Request,
    clock: AttendanceClockIn,
    user_data: Tuple[str, str, str] = Depends(require_role(["employee"]))
):
    user_id, org_id, role = user_data
    emp = await get_employee_by_user_id(user_id, org_id)
    if not emp or emp["id"] != clock.employee_id:
        raise HTTPException(status_code=403, detail="Not authorised to clock in for this employee")
    client = get_supabase()
    today = date.today().isoformat()
    existing = await run_sync_db_call(
        client.table("hr_attendance")
        .select("id")
        .eq("employee_id", clock.employee_id)
        .eq("date", today)
        .is_("clock_out", "null")
        .limit(1)
        .execute
    )
    if existing.data:
        raise HTTPException(status_code=400, detail="Already clocked in today; please clock out first")
    data = {
        "employee_id": clock.employee_id,
        "branch_id": (emp.get("branch_id") if emp else None) or await resolve_request_branch_for_write(request, user_id, org_id, role),
        "date": today,
        "clock_in": clock.clock_in.isoformat(),
        "status": "present"
    }
    result = await run_sync_db_call(client.table("hr_attendance").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to clock in")
    return {"message": "Clocked in", "attendance": result.data[0]}

@hr_router.post("/attendance/clock-out")
async def clock_out(
    request: Request,
    clock: AttendanceClockOut,
    user_data: Tuple[str, str, str] = Depends(require_role(["employee"]))
):
    user_id, org_id, _ = user_data
    emp = await get_employee_by_user_id(user_id, org_id)
    if not emp or emp["id"] != clock.employee_id:
        raise HTTPException(status_code=403, detail="Not authorised")
    client = get_supabase()
    today = date.today().isoformat()
    record = await run_sync_db_call(
        client.table("hr_attendance")
        .select("id")
        .eq("employee_id", clock.employee_id)
        .eq("date", today)
        .is_("clock_out", "null")
        .limit(1)
        .execute
    )
    if not record.data:
        raise HTTPException(status_code=400, detail="No open clock-in found for today")
    update_data = {
        "clock_out": clock.clock_out.isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    result = await run_sync_db_call(
        client.table("hr_attendance")
        .update(update_data)
        .eq("id", record.data[0]["id"])
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to clock out")
    return {"message": "Clocked out", "attendance": result.data[0]}

@hr_router.get("/attendance")
async def get_attendance(
    request: Request,
    employee_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 100,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()
    target_employee_id = employee_id
    if role == "employee":
        emp = await get_employee_by_user_id(user_id, org_id)
        if not emp:
            raise HTTPException(status_code=404, detail="No employee profile")
        if employee_id and employee_id != emp["id"]:
            raise HTTPException(status_code=403, detail="Can only view own attendance")
        target_employee_id = emp["id"]

    selected_branch = await resolve_request_branch(request, user_id, org_id, role)
    visible_user_ids = await get_visible_user_ids(user_id, org_id, role)

    query = client.table("hr_attendance").select("*").eq("org_id", org_id)
    if target_employee_id:
        query = query.eq("employee_id", target_employee_id)
    if start_date:
        query = query.gte("date", start_date.isoformat())
    if end_date:
        query = query.lte("date", end_date.isoformat())
    if selected_branch:
        query = query.eq("branch_id", selected_branch)
    result = await run_sync_db_call(query.order("date", desc=True).range(offset, offset + limit - 1).execute)
    rows = result.data or []

    if visible_user_ids is not None:
        hr_emp_ids_res = await run_sync_db_call(
            client.table("hr_employees").select("id, user_id")
            .eq("org_id", org_id)
            .in_("user_id", list(visible_user_ids))
            .execute
        )
        allowed_emp_ids = {r["id"] for r in (hr_emp_ids_res.data or [])}
        rows = [r for r in rows if r.get("employee_id") in allowed_emp_ids]

    return {"attendance": rows, "total": len(rows)}

@hr_router.post("/leave-requests")
async def create_leave_request(
    request: Request,
    leave: LeaveRequestCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["employee"]))
):
    user_id, org_id, role = user_data
    emp = await get_employee_by_user_id(user_id, org_id)
    if not emp or emp["id"] != leave.employee_id:
        raise HTTPException(status_code=403, detail="Not authorised")
    if leave.start_date > leave.end_date:
        raise HTTPException(status_code=400, detail="Start date must be before end date")
    client = get_supabase()
    data = leave.dict()
    if data.get("start_date"): data["start_date"] = data["start_date"].isoformat()
    if data.get("end_date"): data["end_date"] = data["end_date"].isoformat()
    data["org_id"] = org_id
    data["branch_id"] = (emp.get("branch_id") if emp else None) or await resolve_request_branch_for_write(request, user_id, org_id, role)
    data["status"] = "pending"
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await run_sync_db_call(client.table("hr_leave_requests").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create leave request")
    return result.data[0]

@hr_router.get("/leave-requests")
async def list_leave_requests(
    request: Request,
    employee_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()
    target_employee_id = employee_id
    if role == "employee":
        emp = await get_employee_by_user_id(user_id, org_id)
        if not emp:
            raise HTTPException(status_code=404, detail="No employee profile")
        if employee_id and employee_id != emp["id"]:
            raise HTTPException(status_code=403, detail="Can only view own leave requests")
        target_employee_id = emp["id"]

    selected_branch = await resolve_request_branch(request, user_id, org_id, role)
    visible_user_ids = await get_visible_user_ids(user_id, org_id, role)

    query = client.table("hr_leave_requests").select("*").eq("org_id", org_id)
    if target_employee_id:
        query = query.eq("employee_id", target_employee_id)
    if status:
        query = query.eq("status", status)
    if selected_branch:
        query = query.eq("branch_id", selected_branch)
    result = await run_sync_db_call(query.order("created_at", desc=True).range(offset, offset + limit - 1).execute)
    rows = result.data or []

    if visible_user_ids is not None:
        hr_emp_ids_res = await run_sync_db_call(
            client.table("hr_employees").select("id, user_id")
            .eq("org_id", org_id)
            .in_("user_id", list(visible_user_ids))
            .execute
        )
        allowed_emp_ids = {r["id"] for r in (hr_emp_ids_res.data or [])}
        rows = [r for r in rows if r.get("employee_id") in allowed_emp_ids]

    return {"requests": rows, "total": len(rows)}

@hr_router.put("/leave-requests/{request_id}")
async def update_leave_request(
    request: Request,
    request_id: int,
    update: LeaveRequestUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()
    req = await run_sync_db_call(
        client.table("hr_leave_requests")
        .select("*")
        .eq("id", request_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute
    )
    if not req.data:
        raise HTTPException(status_code=404, detail="Leave request not found")
    if req.data[0]["status"] != "pending":
        raise HTTPException(status_code=400, detail="Request already processed")
    update_data = {
        "status": update.status,
        "approved_by": update.approved_by,
        "notes": update.notes,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    result = await run_sync_db_call(
        client.table("hr_leave_requests")
        .update(update_data)
        .eq("id", request_id)
        .eq("org_id", org_id)
        .execute
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update leave request")
    return result.data[0]

@hr_router.get("/leave-balances")
async def get_leave_balances(
    request: Request,
    employee_id: Optional[int] = None,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()
    target_employee_id = employee_id
    if role == "employee":
        emp = await get_employee_by_user_id(user_id, org_id)
        if not emp:
            raise HTTPException(status_code=404, detail="No employee profile")
        if employee_id and employee_id != emp["id"]:
            raise HTTPException(status_code=403, detail="Can only view own balances")
        target_employee_id = emp["id"]
    query = client.table("hr_leave_balances").select("*").eq("org_id", org_id)
    if target_employee_id:
        query = query.eq("employee_id", target_employee_id)
    result = await run_sync_db_call(query.execute)
    return {"balances": result.data}

@hr_router.post("/payroll/generate")
async def generate_payroll(
    request: Request,
    payload: PayrollGenerate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "finance"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()
    employees = await run_sync_db_call(
        client.table("hr_employees")
        .select("id, salary")
        .eq("org_id", org_id)
        .eq("status", "active")
        .execute
    )
    if not employees.data:
        raise HTTPException(status_code=400, detail="No active employees")
    payrolls = []
    month = payload.month
    year = payload.year
    for emp in employees.data:
        existing = await run_sync_db_call(
            client.table("hr_payroll")
            .select("id")
            .eq("employee_id", emp["id"])
            .eq("month", month)
            .eq("year", year)
            .eq("org_id", org_id)
            .limit(1)
            .execute
        )
        if existing.data:
            continue
        branch_id_for_payroll = await resolve_request_branch_for_write(request, user_id, org_id, role)
        payroll_data = {
            "org_id": org_id,
            "branch_id": branch_id_for_payroll,
            "employee_id": emp["id"],
            "month": month,
            "year": year,
            "base_salary": emp["salary"],
            "allowances": 0.0,
            "deductions": 0.0,
            "net_pay": emp["salary"],
            "status": "draft",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        payrolls.append(payroll_data)
    if payrolls:
        result = await run_sync_db_call(client.table("hr_payroll").insert(payrolls).execute)
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to generate payroll")
    return {"message": f"Generated payroll for {len(payrolls)} employees", "payrolls": result.data if payrolls else []}

@hr_router.get("/payroll")
async def list_payroll(
    request: Request,
    employee_id: Optional[int] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "finance", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()
    target_employee_id = employee_id
    if role == "employee":
        emp = await get_employee_by_user_id(user_id, org_id)
        if not emp:
            raise HTTPException(status_code=404, detail="No employee profile")
        if employee_id and employee_id != emp["id"]:
            raise HTTPException(status_code=403, detail="Can only view own payroll")
        target_employee_id = emp["id"]

    selected_branch = await resolve_request_branch(request, user_id, org_id, role)
    visible_user_ids = await get_visible_user_ids(user_id, org_id, role)

    query = client.table("hr_payroll").select("*").eq("org_id", org_id)
    if target_employee_id:
        query = query.eq("employee_id", target_employee_id)
    if month:
        query = query.eq("month", month)
    if year:
        query = query.eq("year", year)
    if selected_branch:
        query = query.eq("branch_id", selected_branch)
    result = await run_sync_db_call(query.order("year", desc=True).order("month", desc=True).range(offset, offset + limit - 1).execute)
    rows = result.data or []

    if visible_user_ids is not None:
        hr_emp_ids_res = await run_sync_db_call(
            client.table("hr_employees").select("id, user_id")
            .eq("org_id", org_id)
            .in_("user_id", list(visible_user_ids))
            .execute
        )
        allowed_emp_ids = {r["id"] for r in (hr_emp_ids_res.data or [])}
        rows = [r for r in rows if r.get("employee_id") in allowed_emp_ids]

    return {"payroll": rows, "total": len(rows)}

# ===================== INCLUDE ROUTERS =====================


# ===================== HR TASKS & NOTIFICATIONS =====================
class TaskCreate(BaseModel):
    employee_id: int
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    priority: Literal["Low", "Normal", "High"] = "Normal"
    due_date: Optional[date] = None

class TaskUpdate(BaseModel):
    status: Literal["Pending", "In Progress", "Completed"]

@hr_router.get("/tasks")
async def list_tasks(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()

    query = client.table("hr_tasks").select("*, hr_employees(first_name, last_name)").eq("org_id", org_id)
    
    if role == "employee":
        emp = await get_employee_by_user_id(user_id, org_id)
        if not emp:
            return {"tasks": []}
        query = query.eq("employee_id", emp["id"])

    result = await run_sync_db_call(query.order("created_at", desc=True).execute)
    return {"tasks": result.data or []}

@hr_router.post("/tasks")
async def create_task(
    request: Request,
    task: TaskCreate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, _ = user_data
    client = get_supabase()

    data = task.dict()
    if data.get("due_date"):
        data["due_date"] = data["due_date"].isoformat()
    
    data["org_id"] = org_id
    data["assigned_by"] = user_id
    
    result = await run_sync_db_call(client.table("hr_tasks").insert(data).execute)
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create task")
    return result.data[0]

@hr_router.put("/tasks/{task_id}")
async def update_task_status(
    request: Request,
    task_id: int,
    update: TaskUpdate,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()

    query = client.table("hr_tasks").update({"status": update.status}).eq("id", task_id).eq("org_id", org_id)
    
    if role == "employee":
        emp = await get_employee_by_user_id(user_id, org_id)
        if not emp:
            raise HTTPException(403, "Unauthorized")
        query = query.eq("employee_id", emp["id"])

    result = await run_sync_db_call(query.execute)
    if not result.data:
        raise HTTPException(404, "Task not found or unauthorized")
    return result.data[0]

@hr_router.get("/notifications")
async def get_notifications(
    request: Request,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    user_id, org_id, role = user_data
    client = get_supabase()

    query = client.table("hr_notifications").select("*").eq("org_id", org_id).eq("is_read", False)
    
    if role == "employee":
        emp = await get_employee_by_user_id(user_id, org_id)
        if not emp:
            return {"notifications": [], "count": 0}
        query = query.eq("employee_id", emp["id"])

    result = await run_sync_db_call(query.order("created_at", desc=True).execute)
    return {"notifications": result.data or [], "count": len(result.data or [])}

@hr_router.put("/notifications/{notification_id}/read")
async def mark_notification_read(
    request: Request,
    notification_id: int,
    user_data: Tuple[str, str, str] = Depends(require_role(["owner", "admin", "hr", "employee"]))
):
    await rate_limit(get_client_ip(request), user_data[1], request=request)
    _, org_id, _ = user_data
    client = get_supabase()

    result = await run_sync_db_call(
        client.table("hr_notifications").update({"is_read": True})
        .eq("id", notification_id).eq("org_id", org_id).execute
    )
    return {"success": True}
