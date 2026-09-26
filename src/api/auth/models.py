from pydantic import BaseModel
from typing import List, Optional

# --- REQUEST MODELS ---


class UserRegister(BaseModel):
    username: str
    password: str
    email: str
    role: str  # 'Admin', 'ReviewDirector', 'Reviewee'


class UserLogin(BaseModel):
    username: str
    password: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str


class UpdateUserRequest(BaseModel):
    user_id: int
    username: str
    email: str


class DeleteUserRequest(BaseModel):
    user_id: int


# --- RESPONSE MODELS ---


class AuthResponse(BaseModel):
    status: str
    id: str
    email: str
    role: Optional[str] = None


class UserItem(BaseModel):
    id: int
    username: str
    email: str
    role: str
    status: str


class GenericResponse(BaseModel):
    status: str
    message: Optional[str] = None
    id: Optional[str] = None


class ToggleUserStatusRequest(BaseModel):
    user_id: int
    target_status: str


class DeleteResponse(BaseModel):
    status: str
