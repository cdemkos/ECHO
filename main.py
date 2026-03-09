# main.py – ECHO Second Brain (Multi-User mit JWT + FastAPI Users)
# Stand: März 2026

from datetime import datetime, timedelta
from typing import Optional, Annotated
import uuid
from pathlib import Path
import zipfile
import io
import os
import shutil
import json

from fastapi import Depends, HTTPException, status, Request, Response
from fastapi_users import FastAPIUsers, models
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users import BaseUserManager, IntegerIDMixin, exceptions
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext

from nicegui import ui, app
from nicegui.elements.mixins.value_element import ValueElement
from weasyprint import HTML

# Lokale Module (angepasst für Multi-User)
from database import NoteDB  # Muss angepasst werden – siehe unten
from llm import generate_summary
from embedder import get_embedding

# ======================
# Konfiguration
# ======================
SECRET = "your-super-secret-key-change-this"  # Ändere das in Produktion!
JWT_SECRET = "your-jwt-secret-key-change-this"  # Ändere das!
DATABASE_URL = "sqlite+aiosqlite:///data/users.db"  # Haupt-DB für Users

Base = declarative_base()

# ======================
# User Model (FastAPI Users)
# ======================
class User(Base, models.BaseUser):
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class UserCreate(models.BaseUserCreate):
    username: str
    email: EmailStr | None = None
    password: str

class UserUpdate(models.BaseUserUpdate):
    username: str | None = None
    email: EmailStr | None = None
    password: str | None = None

class UserRead(models.BaseUserRead):
    id: int
    username: str
    email: EmailStr | None
    is_active: bool
    is_superuser: bool

# ======================
# User Manager
# ======================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class UserManager(IntegerIDMixin, BaseUserManager[User, int]):
    user_db_model = User
    reset_password_token_secret = JWT_SECRET
    verification_token_secret = JWT_SECRET

    async def validate_password(
        self,
        password: str,
        user: User,
    ) -> None:
        if not pwd_context.verify(password, user.hashed_password):
            raise exceptions.InvalidPasswordException()

    async def on_after_register(self, user: User, request: Request | None = None):
        print(f"User {user.username} registered")

    async def on_after_login(self, user: User, request: Request | None = None):
        print(f"User {user.username} logged in")

# ======================
# Auth Backend (JWT)
# ======================
def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=JWT_SECRET, lifetime_seconds=3600 * 24 * 7)  # 7 Tage

bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")

auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

# ======================
# FastAPI Users Instanz
# ======================
user_db = SQLAlchemyUserDatabase(async_sessionmaker(bind=create_async_engine(DATABASE_URL)), User)

fastapi_users = FastAPIUsers[User, int](
    get_user_manager=lambda: UserManager(user_db),
    [auth_backend],
)

current_user = fastapi_users.current_user()

# ======================
# NiceGUI Auth Wrapper
# ======================
async def get_current_user(request: Request) -> Optional[User]:
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        strategy = get_jwt_strategy()
        data = await strategy.read_token(token)
        user_id = data["sub"]
        async with user_db.session() as session:
            user = await user_db.get_by_id(user_id)
        return user
    except:
        return None

# ======================
# User-spezifische DB & Collection
# ======================
async def get_user_db(user: User) -> NoteDB:
    user_dir = Path("data/users") / f"user_{user.id}"
    user_dir.mkdir(parents=True, exist_ok=True)
    
    db_path = user_dir / "notes.db"
    notes_dir = user_dir / "notes"
    chroma_dir = user_dir / "chroma"
    
    notes_dir.mkdir(exist_ok=True)
    chroma_dir.mkdir(exist_ok=True)
    
    user_db = NoteDB(db_path=str(db_path), chroma_dir=str(chroma_dir), notes_dir=str(notes_dir))
    return user_db

# ======================
# Login / Register Seite
# ======================
@ui.page('/')
async def index(request: Request):
    user = await get_current_user(request)
    if not user:
        return ui.navigate.to('/login')

    # User ist eingeloggt → normale Oberfläche laden
    global reflection_dialog, reflection_content, linking_dialog, linking_content, merge_button

    user_db = await get_user_db(user)

    # Header
    with ui.column().classes('items-center w-full mb-12'):
        ui.label(f'ECHO – {user.username}').classes('text-7xl font-black text-indigo-400 tracking-widest drop-shadow-2xl')
        ui.label('dein lokaler Stream-of-Thought Second Brain').classes('text-2xl text-slate-300 mt-3 font-light italic')

    # Logout-Button oben rechts
    with ui.row().classes('absolute top-4 right-4'):
        ui.button('Logout', on_click=lambda: logout(request)).props('flat color=red-8')

    # Rest der Seite (Eingabe, Suche, Schnellzugriff) – angepasst mit user_db
    # ... (kopiere hier den Rest der alten index()-Funktion rein, aber ersetze db durch user_db)

    # Beispiel: save_thought mit user_db
    async def save_thought(auto: bool = False):
        # ... wie vorher, aber mit user_db statt db
        pass  # passe alle db-Aufrufe an user_db an

    # Reflexion, Suche, etc. analog anpassen

# ======================
# Login-Seite
# ======================
@ui.page('/login')
async def login_page():
    ui.label('Login zu ECHO').classes('text-4xl font-bold mb-8 text-center')

    username_input = ui.input('Benutzername').classes('w-80')
    password_input = ui.input('Passwort', password=True).classes('w-80')

    async def do_login():
        try:
            user = await fastapi_users.get_user_manager().authenticate(
                credentials={"username": username_input.value, "password": password_input.value}
            )
            if user:
                token = await get_jwt_strategy().write_token({"sub": str(user.id)})
                response = Response()
                response.set_cookie(key="access_token", value=token, httponly=True)
                ui.navigate.to('/')
            else:
                ui.notify('Login fehlgeschlagen', type='negative')
        except Exception as e:
            ui.notify(f'Fehler: {str(e)}', type='negative')

    ui.button('Login', on_click=do_login).classes('mt-6 w-80')

    with ui.row().classes('mt-4 text-center'):
        ui.label('Noch kein Account? ')
        ui.link('Registrieren', '/register').classes('text-indigo-400 hover:underline')

# ======================
# Register-Seite
# ======================
@ui.page('/register')
async def register_page():
    ui.label('Registrierung').classes('text-4xl font-bold mb-8 text-center')

    username_input = ui.input('Benutzername').classes('w-80')
    password_input = ui.input('Passwort', password=True).classes('w-80')
    password_confirm = ui.input('Passwort wiederholen', password=True).classes('w-80')

    async def do_register():
        if password_input.value != password_confirm.value:
            ui.notify('Passwörter stimmen nicht überein', type='negative')
            return

        try:
            user = await fastapi_users.get_user_manager().create(
                UserCreate(username=username_input.value, password=password_input.value)
            )
            ui.notify('Registrierung erfolgreich! Du kannst dich jetzt einloggen.', type='positive')
            ui.navigate.to('/login')
        except Exception as e:
            ui.notify(f'Fehler bei Registrierung: {str(e)}', type='negative')

    ui.button('Registrieren', on_click=do_register).classes('mt-6 w-80')

    ui.link('Zurück zum Login', '/login').classes('mt-4 text-indigo-400 hover:underline')

# ======================
# Logout
# ======================
async def logout(request: Request):
    response = Response()
    response.delete_cookie("access_token")
    ui.navigate.to('/login')

# ======================
# FastAPI Users Routes einhängen
# ======================
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)

app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)

# ======================
# Rest der Hilfsfunktionen (angepasst für current_user)
# ======================
# ... (generate_tags, generate_weekly_reflection, export_all, edit_note, etc.)
# Ersetze überall db durch (await get_user_db(await current_user()))

# Beispiel für generate_weekly_reflection mit User-DB:
async def generate_weekly_reflection():
    user = await current_user()
    if not user:
        ui.notify('Nicht authentifiziert', type='negative')
        return

    user_db = await get_user_db(user)
    # ... Rest wie vorher, aber mit user_db statt db

ui.run(
    title='ECHO – Multi-User Second Brain',
    port=9876,
    dark=True,
    reload=True,
    show=True
)
