import datetime
import uuid
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

Base = declarative_base()

class AgentManifestTable(Base):
    __tablename__ = 'agent_manifests'
    
    id = Column(String, primary_key=True)  # e.g., 'support-triage'
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    versions = relationship("AgentVersionTable", back_populates="manifest")
    instances = relationship("AgentInstanceTable", back_populates="manifest")

class AgentVersionTable(Base):
    __tablename__ = 'agent_versions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    manifest_id = Column(String, ForeignKey('agent_manifests.id'), nullable=False)
    version = Column(Integer, nullable=False)
    manifest_yaml = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    manifest = relationship("AgentManifestTable", back_populates="versions")

class UserTable(Base):
    __tablename__ = 'users'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    instances = relationship("AgentInstanceTable", back_populates="user")
    tasks = relationship("TaskTable", back_populates="user")

class AgentInstanceTable(Base):
    __tablename__ = 'agent_instances'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    manifest_id = Column(String, ForeignKey('agent_manifests.id'), nullable=False)
    version = Column(Integer, nullable=False)
    status = Column(String, default='REGISTERED')  # REGISTERED, INITIALIZING, RUNNING, SLEEPING, TERMINATED
    user_id = Column(String, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    manifest = relationship("AgentManifestTable", back_populates="instances")
    tasks = relationship("TaskTable", back_populates="instance")
    user = relationship("UserTable", back_populates="instances")

class TaskTable(Base):
    __tablename__ = 'tasks'
    
    id = Column(String, primary_key=True, default=lambda: f"task_{uuid.uuid4().hex[:8]}")
    instance_id = Column(String, ForeignKey('agent_instances.id'), nullable=False)
    user_id = Column(String, ForeignKey('users.id'), nullable=True)
    input_data = Column(Text, nullable=False)
    status = Column(String, default='QUEUED')  # QUEUED, RUNNING, COMPLETED, FAILED
    priority = Column(String, default='medium')  # low, medium, high
    max_tokens = Column(Integer, nullable=True)
    max_usd = Column(Float, nullable=True)
    output_data = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    llm_provider = Column(String, nullable=True)
    llm_api_key = Column(String, nullable=True)
    
    instance = relationship("AgentInstanceTable", back_populates="tasks")
    checkpoints = relationship("CheckpointTable", back_populates="task")
    user = relationship("UserTable", back_populates="tasks")
    tool_calls = relationship("ToolCallTable", back_populates="task")

class CheckpointTable(Base):
    __tablename__ = 'checkpoints'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, ForeignKey('tasks.id'), nullable=False)
    step_index = Column(Integer, nullable=False)
    state_data = Column(Text, nullable=False)  # Serialized state JSON
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    task = relationship("TaskTable", back_populates="checkpoints")

class ToolCallTable(Base):
    __tablename__ = 'tool_calls'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String, ForeignKey('tasks.id'), nullable=False)
    tool_name = Column(String, nullable=False)
    arguments = Column(Text, nullable=False)  # JSON args
    result = Column(Text, nullable=True)
    status = Column(String, default='ALLOWED')  # ALLOWED, DENIED, SUCCESS, FAILED
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    task = relationship("TaskTable", back_populates="tool_calls")


class SemanticMemoryTable(Base):
    __tablename__ = 'semantic_memories'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    embedding = Column(Text, nullable=False)  # JSON-serialized list of floats
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# DB engine helper
import os
DB_URL = os.getenv("DATABASE_URL", "sqlite:///./agentos.db")
if DB_URL.startswith("sqlite"):
    engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
