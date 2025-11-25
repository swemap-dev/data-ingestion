#include <iostream>
#include <map>
#include <filesystem>
namespace fs = std::filesystem;

// Occurrence of a token in the codebase
struct Occurrence {
    std::string repo;      // repo name or path
    std::string file;      // relative file path
    int line;              // 1-based line number

    // TODO: later
    std::string commit;    // git commit hash
    std::string author;    // author from blame
    std::string timestamp; // ISO timestamp
};

// Index: token -> list of occurrences
using InvertedIndex = std::map<std::string, std::vector<Occurrence>>;

// FileInfo: for gathering files before parallel processing
struct FileInfo {
    std::string repo;        // repo name/path
    std::string rel_path;    // path relative to repo root
    bool is_dependency_file; // true for Cargo.toml, package.json, etc.
};

InvertedIndex build_index_for_repo_parallel(const fs::path& repo_root);
InvertedIndex build_index_for_repo_sequential(const fs::path& repo_root);