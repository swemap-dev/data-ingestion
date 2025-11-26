#include <fstream>
#include <cctype>
#include <vector>
#include <string>
#include <omp.h>
#include <iomanip>
#include <sstream>

#include "repo_reader.h"

using InvertedIndex = std::map<std::string, std::vector<Occurrence>>;

/*
----------------------
Checker Functions
----------------------
*/
// Check if we should skip a directory (e.g., .git, node_modules)
bool should_skip_dir(const fs::path& dir) {
    std::string name = dir.filename().string();
    return (name == ".git" || name == "node_modules" ||
            name == "target" || name == "build" ||
            name == ".idea" || name == ".vscode");
}

// Is this a source-code file we care about? Expand this to take in more sources
bool is_source_file(const fs::path& p) {
    std::string ext = p.extension().string();
    return (ext == ".rs" || ext == ".js" || ext == ".ts" ||
            ext == ".py" || ext == ".cpp" || ext == ".hpp" ||
            ext == ".h"  || ext == ".c"   || ext == ".java");
}

// Is this a dependency file?
bool is_dependency_file(const fs::path& p) {
    std::string name = p.filename().string();
    return (name == "Cargo.toml" ||
            name == "package.json" ||
            name == "requirements.txt" ||
            name == "pyproject.toml");
}

/*
----------------------
Utility Functions
----------------------
*/

// Collect FileInfo entries from a repo root
std::vector<FileInfo> collect_files(const fs::path& repo_root) {
    std::vector<FileInfo> files;
    std::string repo_name = repo_root.filename().string();

    for (auto it = fs::recursive_directory_iterator(repo_root);
         it != fs::recursive_directory_iterator(); ++it) {

        const auto& entry = *it;
        const auto path = entry.path();

        if (entry.is_directory()) {
            if (should_skip_dir(path)) {
                it.disable_recursion_pending(); // do not enter this dir
            }
            continue;
        }

        if (!entry.is_regular_file()) { continue; }

        if (!is_source_file(path) && !is_dependency_file(path)) { continue; }

        bool dep = is_dependency_file(path);
        fs::path rel = fs::relative(path, repo_root);

        files.push_back(FileInfo{
            repo_name,
            rel.string(),
            dep
        });
    }

    return files;
}

// tiny lexer; TODO: expand this to ignore keywords, detect imports, etc
std::vector<std::string> tokenize_line(const std::string& line) {
    std::vector<std::string> tokens;
    std::string cur;

    auto flush = [&]() {
        if (!cur.empty()) {
            tokens.push_back(cur);
            cur.clear();
        }
    };

    for (char ch : line) {
        if (std::isalnum(static_cast<unsigned char>(ch)) || ch == '_' || ch == ':' ) {
            cur.push_back(ch);
        } else {
            flush();
        }
    }
    flush();

    return tokens;
}

void process_source_file(const fs::path& full_path,
                         const FileInfo& info,
                         InvertedIndex& local_index) {
    std::ifstream in(full_path);
    if (!in) return;

    std::string line;
    int line_no = 0;
    while (std::getline(in, line)) {
        ++line_no;
        auto tokens = tokenize_line(line);

        for (const auto& tok : tokens) {
            if (tok.empty()) continue;

            // Very naive filtering: skip too-short tokens, etc.
            if (tok.size() <= 1) continue;

            Occurrence occ;
            occ.repo = info.repo;
            occ.file = info.rel_path;
            occ.line = line_no;

            local_index[tok].push_back(std::move(occ));
        }
    }
}

void process_dependency_file(const fs::path& full_path,
                             const FileInfo& info,
                             InvertedIndex& local_index) {
    std::ifstream in(full_path);
    if (!in) return;

    std::string line;
    int line_no = 0;
    while (std::getline(in, line)) {
        ++line_no;

        // super-naive: grab "words" from the line as candidate package names
        auto tokens = tokenize_line(line);
        for (const auto& tok : tokens) {
            if (tok.empty()) continue;

            // You may refine: only keep lowercase tokens, or ones under [dependencies], etc.
            Occurrence occ;
            occ.repo = info.repo;
            occ.file = info.rel_path;
            occ.line = line_no;

            local_index[tok].push_back(std::move(occ));
        }
    }
}

std::string json_escape(const std::string& s) {
    std::ostringstream out;
    out << '"';
    for (char c : s) {
        switch (c) {
            case '"':  out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\b': out << "\\b";  break;
            case '\f': out << "\\f";  break;
            case '\n': out << "\\n";  break;
            case '\r': out << "\\r";  break;
            case '\t': out << "\\t";  break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    out << "\\u" << std::hex << std::setw(4)
                        << std::setfill('0') << int(c);
                } else {
                    out << c;
                }
        }
    }
    out << '"';
    return out.str();
}

void write_index_to_json(const InvertedIndex& index,
                         const std::string& output_path) {
    std::ofstream out(output_path);
    if (!out) {
        throw std::runtime_error("Cannot open output file: " + output_path);
    }

    out << "{\n";
    bool first_token = true;

    for (const auto& kv : index) {
        if (!first_token) out << ",\n";
        first_token = false;

        const std::string& token = kv.first;
        const std::vector<Occurrence>& occs = kv.second;

        out << "  " << json_escape(token) << ": [\n";

        bool first_occ = true;
        for (const auto& occ : occs) {
            if (!first_occ) out << ",\n";
            first_occ = false;

            out << "    {\n"
                << "      \"repo\": " << json_escape(occ.repo) << ",\n"
                << "      \"file\": " << json_escape(occ.file) << ",\n"
                << "      \"line\": " << occ.line << ",\n"
                << "      \"commit\": " << json_escape(occ.commit) << ",\n"
                << "      \"author\": " << json_escape(occ.author) << ",\n"
                << "      \"timestamp\": " << json_escape(occ.timestamp) << "\n"
                << "    }";
        }

        out << "\n  ]";
    }

    out << "\n}\n";
    out.close();

    std::cout << "Wrote JSON index to " << output_path << "\n";
}

std::vector<std::string> splitStringBySlash(const std::string& inputString) {
    std::vector<std::string> parts;
    std::stringstream ss(inputString);
    std::string segment;
    char delimiter = '/';

    while (std::getline(ss, segment, delimiter)) {
        parts.push_back(segment);
    }
    return parts;
}

InvertedIndex build_index_for_repo_parallel(const fs::path& repo_root) {
    std::vector<FileInfo> files = collect_files(repo_root);

    int num_threads = omp_get_max_threads();
    std::vector<InvertedIndex> local_indexes(num_threads);

    // Parallel over files
    #pragma omp parallel for schedule(dynamic)
    for (int i = 0; i < static_cast<int>(files.size()); ++i) {
        int tid = omp_get_thread_num();
        FileInfo& info = files[i];

        fs::path full_path = repo_root / info.rel_path;

        if (info.is_dependency_file) {
            process_dependency_file(full_path, info, local_indexes[tid]);
        } else {
            process_source_file(full_path, info, local_indexes[tid]);
        }
    }

    // Merge local indexes into a single global index
    InvertedIndex global_index;

    for (auto& local : local_indexes) {
        for (auto& kv : local) {
            const std::string& token = kv.first;
            auto& occs = kv.second;

            auto& dest_vec = global_index[token];
            dest_vec.insert(dest_vec.end(),
                            std::make_move_iterator(occs.begin()),
                            std::make_move_iterator(occs.end()));
        }
    }

    return global_index;
}

InvertedIndex build_index_for_repo_sequential(const fs::path& repo_root) {
    std::vector<FileInfo> files = collect_files(repo_root);
    InvertedIndex index;

    for (const auto& info : files) {
        fs::path full_path = repo_root / info.rel_path;

        if (info.is_dependency_file) {
            process_dependency_file(full_path, info, index);
        } else {
            process_source_file(full_path, info, index);
        }
    }

    return index;
}


int main(int argc, char* argv[]) {
    // check if arguments valid
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <repo_root_path>\n";
        return 1;
    }

    // check if directory valid
    fs::path repo_root = argv[1];
    if (!fs::exists(repo_root) || !fs::is_directory(repo_root)) {
        std::cerr << "Error: " << repo_root << " is not a valid directory.\n";
        return 1;
    }

    try {
        // Sequential benchmark
        double t_seq_start = omp_get_wtime();
        InvertedIndex index_seq = build_index_for_repo_sequential(repo_root);
        double t_seq_end = omp_get_wtime();

        // Parallel benchmark
        double t_par_start = omp_get_wtime();
        InvertedIndex index_par = build_index_for_repo_parallel(repo_root);
        double t_par_end = omp_get_wtime();

        std::cout << "[Sequential] Unique tokens: " << index_seq.size()
                  << ", time: " << (t_seq_end - t_seq_start) << " seconds\n";

        std::cout << "[Parallel  ] Unique tokens: " << index_par.size()
                  << ", time: " << (t_par_end - t_par_start) << " seconds\n\n";

        if (index_seq.size() != index_par.size()) {
            std::cerr << "WARNING: sequential and parallel indexes differ in token count!\n";
        }

        // Write JSON output
        std::string repo_name = splitStringBySlash(repo_root.u8string()).back();
        std::string json_path = "../index/" + repo_name + ".json";
        write_index_to_json(index_par, json_path);

    } catch (const std::exception& ex) {
        std::cerr << "Exception: " << ex.what() << "\n";
        return 1;
    }

    return 0;
}

