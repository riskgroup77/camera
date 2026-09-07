from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, get_current_user
from app.models import Building, Camera, Department, Faculty, StudentGroup
from app.schemas.org import (
    DepartmentCreateIn,
    DepartmentOut,
    BuildingCreateIn,
    BuildingOut,
    FacultyCreateIn,
    FacultyOut,
    StudentGroupCreateIn,
    StudentGroupOut,
)

router = APIRouter(prefix="/api", tags=["org-structure"])

# Tashkiliy tuzilma sahifasi frontendda alohida ruxsat talab qilmaydi
# (AdminLayout.tsx NAV_ITEMS'da `permission` maydoni yo'q) — shuning uchun
# bu yerda faqat autentifikatsiya talab qilinadi, aniq huquq emas.
AuthDep = Annotated[CurrentUser, Depends(get_current_user)]


@router.get("/buildings", response_model=list[BuildingOut])
async def list_buildings(db: Annotated[AsyncSession, Depends(get_db)], _: AuthDep) -> list[BuildingOut]:
    """camera_count endi Building.camera_count'dan (hech qachon admin
    tomonidan to'ldirilmaydigan, seed.py'dagi eski demo raqam qolган
    o'lik maydon) emas, balki haqiqatan ro'yxatdan o'tgan Camera
    qatorlaridan hisoblanadi — aks holda "N ta kamera biriktirilgan"
    yozuvi hech qachon qo'shilmagan kameralarni ham hisoblab, admin
    panelida chalkashtirib yuborardi."""
    result = await db.execute(
        select(Building, func.count(Camera.id))
        .outerjoin(Camera, Camera.building_id == Building.id)
        .group_by(Building.id)
        .order_by(Building.name)
    )
    return [BuildingOut(id=str(b.id), name=b.name, camera_count=count) for b, count in result.all()]


@router.post("/buildings", response_model=BuildingOut, status_code=status.HTTP_201_CREATED)
async def create_building(
    body: BuildingCreateIn, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: AuthDep
) -> BuildingOut:
    building = Building(name=body.name, camera_count=body.camera_count)
    db.add(building)
    await log_action(db, request, current_user.id, f"Yangi bino qo'shdi: {body.name}", "Tashkilot")
    await db.commit()
    await db.refresh(building)
    return BuildingOut(id=str(building.id), name=building.name, camera_count=building.camera_count)


@router.patch("/buildings/{building_id}", response_model=BuildingOut)
async def update_building(
    building_id: str,
    body: BuildingCreateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: AuthDep,
) -> BuildingOut:
    result = await db.execute(select(Building).where(Building.id == building_id))
    building = result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bino topilmadi")
    building.name = body.name
    building.camera_count = body.camera_count
    await log_action(db, request, current_user.id, f"Binoni tahrirladi: {body.name}", "Tashkilot")
    await db.commit()
    await db.refresh(building)
    return BuildingOut(id=str(building.id), name=building.name, camera_count=building.camera_count)


@router.delete("/buildings/{building_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_building(
    building_id: str, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: AuthDep
) -> None:
    result = await db.execute(select(Building).where(Building.id == building_id))
    building = result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bino topilmadi")
    await log_action(db, request, current_user.id, f"Binoni o'chirdi: {building.name}", "Tashkilot")
    await db.delete(building)
    await db.commit()


@router.get("/faculties", response_model=list[FacultyOut])
async def list_faculties(db: Annotated[AsyncSession, Depends(get_db)], _: AuthDep) -> list[FacultyOut]:
    result = await db.execute(select(Faculty).order_by(Faculty.name))
    return [
        FacultyOut(id=str(f.id), name=f.name, course_count=f.course_count, student_count=f.student_count)
        for f in result.scalars().all()
    ]


@router.post("/faculties", response_model=FacultyOut, status_code=status.HTTP_201_CREATED)
async def create_faculty(
    body: FacultyCreateIn, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: AuthDep
) -> FacultyOut:
    faculty = Faculty(name=body.name, course_count=body.course_count, student_count=0)
    db.add(faculty)
    await log_action(db, request, current_user.id, f"Yangi fakultet qo'shdi: {body.name}", "Tashkilot")
    await db.commit()
    await db.refresh(faculty)
    return FacultyOut(
        id=str(faculty.id), name=faculty.name, course_count=faculty.course_count, student_count=faculty.student_count
    )


@router.delete("/faculties/{faculty_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faculty(
    faculty_id: str, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: AuthDep
) -> None:
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalar_one_or_none()
    if faculty is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fakultet topilmadi")
    await log_action(db, request, current_user.id, f"Fakultetni o'chirdi: {faculty.name}", "Tashkilot")
    await db.delete(faculty)
    await db.commit()


@router.get("/student-groups", response_model=list[StudentGroupOut])
async def list_student_groups(db: Annotated[AsyncSession, Depends(get_db)], _: AuthDep) -> list[StudentGroupOut]:
    result = await db.execute(select(StudentGroup).options(selectinload(StudentGroup.faculty)).order_by(StudentGroup.name))
    return [
        StudentGroupOut(
            id=str(g.id), name=g.name, faculty=g.faculty.name, course=g.course, student_count=g.student_count
        )
        for g in result.scalars().all()
    ]


@router.post("/student-groups", response_model=StudentGroupOut, status_code=status.HTTP_201_CREATED)
async def create_student_group(
    body: StudentGroupCreateIn, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: AuthDep
) -> StudentGroupOut:
    result = await db.execute(select(Faculty).where(Faculty.id == body.faculty_id))
    faculty = result.scalar_one_or_none()
    if faculty is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fakultet topilmadi")

    group = StudentGroup(name=body.name, faculty_id=faculty.id, course=body.course, student_count=0)
    db.add(group)
    await log_action(db, request, current_user.id, f"Yangi guruh qo'shdi: {body.name}", "Tashkilot")
    await db.commit()
    await db.refresh(group)
    return StudentGroupOut(
        id=str(group.id), name=group.name, faculty=faculty.name, course=group.course, student_count=group.student_count
    )


@router.delete("/student-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student_group(
    group_id: str, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: AuthDep
) -> None:
    result = await db.execute(select(StudentGroup).where(StudentGroup.id == group_id))
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Guruh topilmadi")
    await log_action(db, request, current_user.id, f"Guruhni o'chirdi: {group.name}", "Tashkilot")
    await db.delete(group)
    await db.commit()


# --- Kafedralar ---
#
# Kameralar avval faqat bino bo'yicha guruhlanardi. Bitta binoda o'nlab
# kafedra bo'lgani uchun operator "shu kafedraning kameralari" ni
# ko'rmoqchi bo'lganda butun binoni varaqlashiga to'g'ri kelardi.


@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(db: Annotated[AsyncSession, Depends(get_db)], _: AuthDep) -> list[DepartmentOut]:
    """camera_count binolardagi kabi haqiqiy Camera qatorlaridan
    hisoblanadi, alohida saqlanadigan raqamdan emas — saqlangan raqam
    vaqt o'tib haqiqatdan uzoqlashadi."""
    result = await db.execute(
        select(Department, func.count(Camera.id))
        .outerjoin(Camera, Camera.department_id == Department.id)
        .options(selectinload(Department.building))
        .group_by(Department.id)
        .order_by(Department.name)
    )
    return [
        DepartmentOut(
            id=str(d.id),
            name=d.name,
            building_id=str(d.building_id) if d.building_id else None,
            building_name=d.building.name if d.building else "",
            camera_count=count,
        )
        for d, count in result.all()
    ]


@router.post("/departments", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
async def create_department(
    body: DepartmentCreateIn, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: AuthDep
) -> DepartmentOut:
    building = None
    if body.building_id:
        building = await db.get(Building, body.building_id)
        if building is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bino topilmadi")

    department = Department(name=body.name.strip(), building_id=building.id if building else None)
    db.add(department)
    await log_action(db, request, current_user.id, f"Yangi kafedra qo'shdi: {body.name}", "Tashkilot")
    await db.commit()
    await db.refresh(department)
    return DepartmentOut(
        id=str(department.id),
        name=department.name,
        building_id=str(department.building_id) if department.building_id else None,
        building_name=building.name if building else "",
        camera_count=0,
    )


@router.delete("/departments/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(
    department_id: str, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: AuthDep
) -> None:
    """Kameralar o'chirilmaydi — ular kafedrasiz qoladi va bino bo'yicha
    filtrlanaveradi (Camera.department_id ON DELETE SET NULL)."""
    department = await db.get(Department, department_id)
    if department is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kafedra topilmadi")
    name = department.name
    await db.delete(department)
    await log_action(db, request, current_user.id, f"Kafedrani o'chirdi: {name}", "Tashkilot")
    await db.commit()
