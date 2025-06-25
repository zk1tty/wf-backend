"""
Browser Profile Manager

Clean architecture for managing user profiles and session directories.
Separates user-persistent data from temporary session data.
"""

import os
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class BrowserProfileManager:
    """
    Manages browser profiles and session directories with clean separation:
    
    - User Profiles: Persistent data stored in ~/.browseruse/profiles/{user_id}/
      Contains: cookies, login sessions, preferences, bookmarks
      
    - Session Directories: Temporary data for workflow execution
      Contains: cache, temp files, workflow-specific data
      Cleaned up after each session
    """
    
    def __init__(self):
        self.base_profile_dir = Path.home() / ".browseruse" / "profiles"
        self.base_session_dir = Path(tempfile.gettempdir()) / "browseruse_sessions"
        
        # Ensure base directories exist
        self.base_profile_dir.mkdir(parents=True, exist_ok=True)
        self.base_session_dir.mkdir(parents=True, exist_ok=True)
    
    def get_user_profile_dir(self, user_id: str) -> Path:
        """
        Get or create user profile directory for persistent data.
        
        Args:
            user_id: Unique identifier for the user
            
        Returns:
            Path to user's persistent profile directory
        """
        user_profile_dir = self.base_profile_dir / user_id
        user_profile_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"User profile directory: {user_profile_dir}")
        return user_profile_dir
    
    def get_session_dir(self, session_id: str) -> Path:
        """
        Get or create session directory for temporary data.
        
        Args:
            session_id: Unique identifier for the session
            
        Returns:
            Path to session's temporary directory
        """
        session_dir = self.base_session_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Session directory: {session_dir}")
        return session_dir
    
    def cleanup_session(self, session_id: str) -> bool:
        """
        Clean up session directory after workflow completion.
        
        Args:
            session_id: Session identifier to clean up
            
        Returns:
            True if cleanup successful, False otherwise
        """
        try:
            session_dir = self.base_session_dir / session_id
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
                logger.info(f"Cleaned up session directory: {session_dir}")
                return True
            return True
        except Exception as e:
            logger.error(f"Error cleaning up session {session_id}: {e}")
            return False
    
    def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """
        Clean up old session directories to prevent disk space issues.
        
        Args:
            max_age_hours: Maximum age of sessions to keep (default: 24 hours)
            
        Returns:
            Number of sessions cleaned up
        """
        import time
        
        cleaned_count = 0
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        try:
            for session_dir in self.base_session_dir.iterdir():
                if session_dir.is_dir():
                    # Check if directory is older than max_age
                    dir_age = current_time - session_dir.stat().st_mtime
                    if dir_age > max_age_seconds:
                        shutil.rmtree(session_dir, ignore_errors=True)
                        logger.info(f"Cleaned up old session: {session_dir.name}")
                        cleaned_count += 1
        except Exception as e:
            logger.error(f"Error during old session cleanup: {e}")
        
        logger.info(f"Cleaned up {cleaned_count} old sessions")
        return cleaned_count
    
    def get_user_profile_info(self, user_id: str) -> Dict[str, Any]:
        """
        Get information about user's profile.
        
        Args:
            user_id: User identifier
            
        Returns:
            Dictionary with profile information
        """
        profile_dir = self.get_user_profile_dir(user_id)
        
        # Calculate profile size
        total_size = 0
        file_count = 0
        for root, dirs, files in os.walk(profile_dir):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    total_size += os.path.getsize(file_path)
                    file_count += 1
                except (OSError, IOError):
                    pass
        
        return {
            'user_id': user_id,
            'profile_path': str(profile_dir),
            'exists': profile_dir.exists(),
            'size_bytes': total_size,
            'file_count': file_count,
            'created_time': profile_dir.stat().st_ctime if profile_dir.exists() else None,
            'modified_time': profile_dir.stat().st_mtime if profile_dir.exists() else None
        }
    
    def create_browser_profile_config(self, session_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Create browser profile configuration for session.
        
        Args:
            session_id: Session identifier
            user_id: Optional user identifier for persistent profile features
            
        Returns:
            Configuration dictionary for BrowserProfile
        """
        # Always use session directory for user_data_dir to avoid conflicts
        session_dir = self.get_session_dir(session_id)
        
        config = {
            'user_data_dir': str(session_dir),
            'headless': True,
            'disable_security': True,
            'keep_alive': False,
            'args': [
                '--disable-web-security',
                '--no-first-run',
                '--disable-default-browser-check',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-features=TranslateUI',
                '--disable-ipc-flooding-protection',
                '--new-window'
            ]
        }
        
        # Future enhancement: If user_id provided, copy persistent data
        if user_id:
            logger.info(f"Session {session_id} associated with user {user_id}")
            # TODO: Copy user preferences, cookies, etc. from user profile
            # user_profile_dir = self.get_user_profile_dir(user_id)
            # self._copy_user_data_to_session(user_profile_dir, session_dir)
        
        return config


# Global instance for easy access
profile_manager = BrowserProfileManager() 