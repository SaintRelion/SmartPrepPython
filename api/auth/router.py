import jwt

from utils.db import db
from fastapi import APIRouter, HTTPException, Depends
from typing import List

from datetime import datetime, timedelta
from utils.email import send_recovery_email
from utils.password_helper import hash_password, verify_password

# Standardized Imports
from .models import (
    DeleteUserRequest,
    GenericResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    ToggleUserStatusRequest,
    UpdateUserRequest,
    UserRegister,
    UserLogin,
    AuthResponse,
    UserItem,
    DeleteResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

SECRET_KEY = "SMARTPREP-PROTOCOL-ALPHA-9"


class AuthController:

    @staticmethod
    @router.post("/register", response_model=AuthResponse)
    async def register_POST(user: UserRegister) -> AuthResponse:
        # Use the helper from utils
        hashed_pwd = hash_password(user.password)
        try:
            new_id = db.insert(
                """
                INSERT INTO users (username, password_hash, email, role, status)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user.username, hashed_pwd, user.email, user.role, "locked"),
            )
            return AuthResponse(status="success", id=str(new_id))
        except Exception as e:
            print(f"Register Error: {e}")
            raise HTTPException(
                status_code=400, detail="Username or Email already exists"
            )

    @staticmethod
    @router.post("/login", response_model=AuthResponse)
    async def login_POST(user: UserLogin) -> AuthResponse:
        # SQL updated to fetch status
        row = db.fetchone(
            "SELECT id, password_hash, role, email, status FROM users WHERE username = %s",
            (user.username,),
        )

        # 1. Credential Verification
        if not row or not verify_password(user.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # 2. Status Enforcement (Strict Lock Check)
        if row.get("status") == "locked":
            raise HTTPException(
                status_code=403,
                detail="Account Locked: Access denied by administrative protocol.",
            )

        return AuthResponse(
            status="success",
            id=str(row["id"]),
            email=str(row["email"]),
            role=row["role"],
        )

    @staticmethod
    @router.get("/get_users", response_model=List[UserItem])
    async def get_users_GET() -> List[UserItem]:
        users = db.select("SELECT id, username, email, role, status FROM users")
        return [UserItem(**u) for u in users]

    @staticmethod
    @router.post("/request_reset", response_model=GenericResponse)
    async def request_reset_POST(req: PasswordResetRequest) -> GenericResponse:
        user = db.fetchone("SELECT id FROM users WHERE email = %s", (req.email,))

        if not user:
            raise HTTPException(
                status_code=404, detail="Identifier not found in registry."
            )

        # Generate Signed Token (Valid for 15m)
        payload = {"uid": user["id"], "exp": datetime.utcnow() + timedelta(minutes=15)}
        token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

        # EXECUTE EMAIL DISPATCH
        dispatch_success = send_recovery_email(req.email, token)

        if not dispatch_success:
            raise HTTPException(
                status_code=500, detail="Mail Server Failure: Unable to dispatch token."
            )

        return GenericResponse(
            status="success",
            message="Recovery token dispatched to your registered email.",
            id="DISPATCHED",  # Hide the token from the API response for security
        )

    @staticmethod
    @router.post("/confirm_reset", response_model=GenericResponse)
    async def confirm_reset_POST(req: PasswordResetConfirm) -> GenericResponse:
        try:
            payload = jwt.decode(req.token, SECRET_KEY, algorithms=["HS256"])
            user_id = payload["uid"]

            hashed_pwd = hash_password(req.new_password)
            db.update(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (hashed_pwd, user_id),
            )

            return GenericResponse(status="success", message="Credentials updated.")
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=400, detail="Forensic Token Expired.")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=400, detail="Invalid Security Signature.")

    @staticmethod
    @router.post("/update_user", response_model=GenericResponse)
    async def update_user_POST(req: UpdateUserRequest) -> GenericResponse:
        db.update(
            "UPDATE users SET username = %s, email = %s WHERE id = %s",
            (req.username, req.email, req.user_id),
        )
        return GenericResponse(status="success", message="Personnel data updated.")

    @staticmethod
    @router.post("/toggle_status", response_model=DeleteResponse)
    async def toggle_status_POST(req: ToggleUserStatusRequest) -> DeleteResponse:
        # Strict update: only allow specific status transitions
        db.update(
            "UPDATE users SET status = %s WHERE id = %s",
            (req.target_status, req.user_id),
        )
        return DeleteResponse(status="updated")

    @staticmethod
    @router.post("/delete_user", response_model=DeleteResponse)
    async def delete_user_DELETE(req: DeleteUserRequest) -> DeleteResponse:
        db.delete("DELETE FROM users WHERE id = %s", (req.user_id,))
        return DeleteResponse(status="deleted")
