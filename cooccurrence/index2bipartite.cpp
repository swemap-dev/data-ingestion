#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <unordered_map>
#include <utility>
#include <stdexcept>
#include <omp.h>

#include "index2bipartite.h"

using EdgeMap = std::unordered_map<long long, int>;
namespace fs = std::filesystem;

struct FileInfo { std::string repo; std::string file; };


std::string read_file(const std::string &path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("Could not open file: " + path);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
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

EdgeMap build_edge_map_par(std::unordered_map<std::string, int>& token_to_id,
                           std::unordered_map<std::string, int> file_to_id,
                           std::vector<std::string>& id_to_token, json j) {
    // Parallel edge building with local maps per thread
    std::vector<EdgeMap> thread_maps(omp_get_max_threads());

    #pragma omp parallel for schedule(dynamic)
    for (int i = 0; i < static_cast<int>(id_to_token.size()); ++i) {
        const std::string& token_str = id_to_token[i];
        int token_id = token_to_id[token_str];
        auto& occ_array = j[token_str];

        int tid = omp_get_thread_num();
        auto& local_map = thread_maps[tid];

        for (auto& occ : occ_array) {
            std::string repo = occ.value("repo", "");
            std::string file = occ.value("file", "");
            std::string file_key = repo + "/" + file;
            int file_id = file_to_id[file_key];

            // Encode (file_id, token_id) into 64-bit key
            long long key = ((long long)file_id << 32) | (unsigned int)token_id;
            local_map[key] += 1;
        }
    }

    // Merge all thread-local maps into global edge map
    EdgeMap global_map;
    for (auto& m : thread_maps) {
        for (auto& [key, count] : m) {
            global_map[key] += count;
        }
    }
    
    return global_map;
}

EdgeMap build_edge_map_seq(std::unordered_map<std::string, int>& token_to_id,
                           std::unordered_map<std::string, int>& file_to_id,
                           std::vector<std::string>& id_to_token, json j) {
    // Sequential counting of token occurrences per file
    EdgeMap edge_weight_map;

    for (size_t i = 0; i < id_to_token.size(); ++i) {
        const std::string& token_str = id_to_token[i];
        int token_id = token_to_id[token_str];
        auto& occ_array = j[token_str];

        for (auto& occ : occ_array) {
            std::string repo = occ.value("repo", "");
            std::string file = occ.value("file", "");
            std::string file_key = repo + "/" + file;
            int file_id = file_to_id[file_key];

            long long key = ((long long)file_id << 32) | (unsigned int)token_id;
            edge_weight_map[key] += 1;
        }
    }

    return edge_weight_map;
}

void write_graph(const std::string index_path, EdgeMap& global_map, std::vector<FileInfo>& id_to_file, std::vector<std::string>& id_to_token){
    std::string index_name = splitStringBySlash(index_path).back();
    size_t dot_pos = index_name.find('.');
    std::string repo_name = index_name.substr(0, dot_pos);
    fs::path dir_path = std::string("../graph/") + repo_name;

    // Create directory for the graph
    if (!std::filesystem::exists(dir_path)) {
        // Attempt to create the directory
        std::error_code ec; // For error handling
        if (std::filesystem::create_directory(dir_path, ec)) {
            std::cout << "Directory created successfully: " << dir_path << std::endl;
        } else {
            std::cerr << "Error creating directory: " << dir_path << " - " << ec.message() << std::endl;
        }
    }

    std::string edges_path = dir_path.u8string() + std::string("/edges.txt");
    std::string files_path = dir_path.u8string() + std::string("/files.csv");
    std::string tokens_path = dir_path.u8string() + std::string("/tokens.csv");
    {
        std::ofstream out(edges_path);
        if (!out) throw std::runtime_error("Cannot open " + edges_path);
        for (auto& [key, weight] : global_map) {
            int file_id  = (int)(key >> 32);
            int token_id = (int)(key & 0xffffffff);
            out << file_id << " " << token_id << " " << weight << "\n";
        }
    }

    // Write mappings
    {
        std::ofstream out(files_path);
        out << "file_id,repo,file\n";
        for (size_t fid = 0; fid < id_to_file.size(); ++fid)
            out << fid << "," << id_to_file[fid].repo << "," << id_to_file[fid].file << "\n";
    }
    {
        std::ofstream out(tokens_path);
        out << "token_id,token\n";
        for (size_t tid = 0; tid < id_to_token.size(); ++tid)
            out << tid << "," << id_to_token[tid] << "\n";
    }
    std::cout << "Wrote edges with weights to " << edges_path << "\n";
}


int main(int argc, char* argv[]) {
    const std::string index_path = argv[1];

    try {
        std::string json_str = read_file(index_path);
        json j = json::parse(json_str);
        if (!j.is_object()) throw std::runtime_error("index.json root must be object");

        std::unordered_map<std::string, int> token_to_id;
        std::unordered_map<std::string, int> file_to_id;
        std::vector<std::string> id_to_token;

        // struct FileInfo { std::string repo; std::string file; };
        std::vector<FileInfo> id_to_file;

        int next_token_id = 0;
        int next_file_id  = 0;

        // Pass 1: assign IDs
        for (auto& [token_str, occ_array] : j.items()) {
            if (!occ_array.is_array()) continue;
            if (token_to_id.find(token_str) == token_to_id.end()) {
                token_to_id[token_str] = next_token_id++;
                id_to_token.push_back(token_str);
            }

            for (auto& occ : occ_array) {
                std::string repo = occ.value("repo", "");
                std::string file = occ.value("file", "");
                std::string file_key = repo + "/" + file;
                if (file_to_id.find(file_key) == file_to_id.end()) {
                    file_to_id[file_key] = next_file_id++;
                    id_to_file.push_back(FileInfo{repo, file});
                }
            }
        }

        std::cout << "Unique tokens: " << id_to_token.size()
                  << ", Unique files: " << id_to_file.size() << "\n";

        double t_start_seq = omp_get_wtime();
        EdgeMap global_map = build_edge_map_seq(token_to_id, file_to_id, id_to_token, j);
        double t_end_seq = omp_get_wtime();

        double t_start_par = omp_get_wtime();
        EdgeMap seq_map = build_edge_map_par(token_to_id, file_to_id, id_to_token, j);
        double t_end_par = omp_get_wtime();

        std::cout << "\n[Sequential] Unique file-token pairs: " << global_map.size()
                  << ", time: " << (t_end_seq - t_start_seq) << " seconds\n";
        std::cout << "[Parallel  ] Unique file-token pairs: " << global_map.size()
                  << ", time: " << (t_end_par - t_start_par) << " seconds\n\n";

        write_graph(index_path, global_map, id_to_file, id_to_token);

    } catch (const std::exception& ex) {
        std::cerr << "Error: " << ex.what() << "\n";
        return 1;
    }

    return 0;
}
