from .user_handlers import router as user_router
from .manager_handlers import router as manager_router
from .group_handlers import router as group_router

__all__ = ['user_router', 'manager_router', 'group_router']