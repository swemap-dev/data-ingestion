import os
from typing import List, Set, Dict, Optional

class ModuleResolver:
    """
    Identifies functional modules in a repository based on build system markers.
    """
    
    # Standard build system configuration files
    MODULE_MARKERS = {
        # Java/Kotlin/Android
        "build.gradle", "build.gradle.kts", "pom.xml", "settings.gradle",
        # JavaScript/TypeScript
        "package.json",
        # Rust
        "Cargo.toml",
        # Go
        "go.mod",
        # Python
        "pyproject.toml", "setup.py", "requirements.txt",
        # General/C++
        "CMakeLists.txt", "Makefile"
    }

    # Directories that should never be module roots, even if they contain markers
    IGNORED_DIRS = {
        "node_modules", "target", "build", "dist", "venv", ".git", ".idea", ".vscode"
    }

    def __init__(self, all_file_paths: List[str]):
        """
        Initialize with a list of all file paths in the repository.
        """
        self.all_file_paths = all_file_paths
        self.known_modules = self._discover_modules()

    def _discover_modules(self) -> Set[str]:
        """
        Scans the file list to find all directories containing module markers.
        """
        modules = set()
        
        # Optimize by iterating once. 
        # We need to check if a file's basename is a marker.
        for file_path in self.all_file_paths:
            dirname, basename = os.path.split(file_path)
            
            if basename in self.MODULE_MARKERS:
                # Check if directory should be ignored
                if self._is_ignored(dirname):
                    continue
                modules.add(dirname)
                
        # Always include root as a fallback if not explicitly found?
        # The spec says "Fallback: If the search reaches the Repository Root without finding a marker, the file belongs to the Root_Module."
        # So "ROOT" or "" (empty string for root dir) is implicitly a valid target if we don't find anything else.
        # But we don't strictly need to add it to known_modules for the loop to work if we handle the base case.
        # However, purely for consistency, let's leave it to resolve logic.
        
        return modules

    def _is_ignored(self, dirname: str) -> bool:
        """
        Returns True if the directory path contains any ignored segment.
        """
        parts = dirname.split('/')
        for part in parts:
            if part in self.IGNORED_DIRS:
                return True
        return False

    def resolve_module(self, file_path: str) -> str:
        """
        Finds the nearest parent module for a given file path.
        Returns the directory path of the module (or "" for root).
        """
        current_dir = os.path.dirname(file_path)
        
        # 1. Bubble up
        # We go up until we find a known module or hit root
        while current_dir:
            if current_dir in self.known_modules:
                return current_dir
            
            # Move up
            parent = os.path.dirname(current_dir)
            if parent == current_dir: # Reached root (should be empty string or '/')
                break
            current_dir = parent
            
        # If we reached here, check if root itself is a known module
        # If not, it falls back to root anyway.
        if "" in self.known_modules: # Check empty string key for root
             return ""
             
        # "Fallback: If the search reaches the Repository Root without finding a marker, the file belongs to the Root_Module."
        return ""