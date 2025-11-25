#include <filesystem>
#include <thread>
#include <chrono>

#include "cooccur.h"


std::unordered_map<long long, double>
bipartite_seq(int max_token_id,
              int max_file_id,
              std::vector<std::vector<TokenEdge>>& file_to_tokens){
    std::vector<double> token_norm(max_token_id + 1, 0.0);
    for (int f = 0; f <= max_file_id; ++f) {
        for (auto& e : file_to_tokens[f]) {
            token_norm[e.token_id] += e.weight * e.weight;
        }
    }
    for (auto& n : token_norm) n = std::sqrt(n);

    // Step 4. Compute token-token co-occurrence (normalized)
    std::unordered_map<long long, double> cooccur_map;

    for (int f = 0; f <= max_file_id; ++f) {
        const auto& neigh = file_to_tokens[f];
        if (neigh.size() < 2) continue;

        for (size_t i = 0; i < neigh.size(); ++i) {
            for (size_t j = i + 1; j < neigh.size(); ++j) {
                int t1 = neigh[i].token_id;
                int t2 = neigh[j].token_id;
                if (t1 == t2) continue;
                if (t1 > t2) std::swap(t1, t2);

                double denom = token_norm[t1] * token_norm[t2];
                if (denom == 0) continue;

                double contrib = (neigh[i].weight * neigh[j].weight) / denom;
                long long key = ((long long)t1 << 32) | (unsigned)t2;
                cooccur_map[key] += contrib;
            }
        }
    }
    return cooccur_map;
}


std::vector<Pair>
map_reduce(int max_token_id,
           int max_file_id,
           std::vector<std::vector<TokenEdge>>& file_to_tokens) {
    // Compute per-token norms
    std::vector<double> norm(max_token_id + 1, 0.0);
    for (int f = 0; f <= max_file_id; ++f)
        for (auto& e : file_to_tokens[f])
            norm[e.token_id] += e.weight * e.weight;
    for (auto& n : norm) n = std::sqrt(n);

    // Map output (all key-value pairs)
    std::vector<Pair> intermediate;

    #pragma omp parallel
    {
        std::vector<Pair> local_pairs;

        #pragma omp for schedule(dynamic)
        for (int f = 0; f <= max_file_id; ++f) {
            auto& neigh = file_to_tokens[f];
            if (neigh.size() < 2) continue;

            for (size_t i = 0; i < neigh.size(); ++i) {
                for (size_t j = i + 1; j < neigh.size(); ++j) {
                    int t1 = neigh[i].token_id;
                    int t2 = neigh[j].token_id;
                    if (t1 == t2) continue;
                    if (t1 > t2) std::swap(t1, t2);

                    double denom = norm[t1] * norm[t2];
                    if (denom == 0) continue;
                    double contrib = (neigh[i].weight * neigh[j].weight) / denom;

                    local_pairs.push_back({t1, t2, contrib});
                }
            }
        }

        // Merge local results
        #pragma omp critical
        intermediate.insert(intermediate.end(),
                            local_pairs.begin(), local_pairs.end());
    }

    std::cout << "Map phase emitted " << intermediate.size() << " pairs\n";

    // --------------------- SHUFFLE + REDUCE ----------------------
    // Sort by (t1, t2)
    std::sort(intermediate.begin(), intermediate.end(), PairComparator());
    return intermediate;
}

std::unordered_map<long long, double>
bipartite_taversal(int max_token_id,
                   int max_file_id,
                   std::vector<std::vector<TokenEdge>>& file_to_tokens)
{
    // dense norms array
    std::vector<double> token_norm(max_token_id + 1, 0.0);
    double* norm = token_norm.data();  // pointer to underlying array
    int num_threads = omp_get_max_threads();
    // norm is now the thing we reduce over
    #pragma omp parallel for schedule(static) reduction(+: norm[:max_token_id+1])
    for (int f = 0; f <= max_file_id; ++f) {
        for (auto& e : file_to_tokens[f]) {
            norm[e.token_id] += e.weight * e.weight;
        }
    }

    #pragma omp parallel for schedule(static)
    for (int t = 0; t <= max_token_id; ++t) {
        norm[t] = std::sqrt(norm[t]);
    }

    // Map phase: each thread collects (t1,t2,value) pairs in a vector
    std::vector<std::vector<PairEntry>> thread_pairs(num_threads);

    #pragma omp parallel for schedule(dynamic, 32)
    for (int f = 0; f <= max_file_id; ++f) {
        int tid = omp_get_thread_num();
        auto& local = thread_pairs[tid];
        const auto& neigh = file_to_tokens[f];
        if (neigh.size() < 2) continue;

        for (size_t i = 0; i < neigh.size(); ++i) {
            for (size_t j = i + 1; j < neigh.size(); ++j) {
                int t1 = neigh[i].token_id;
                int t2 = neigh[j].token_id;
                if (t1 == t2) continue;
                if (t1 > t2) std::swap(t1, t2);

                double denom = norm[t1] * norm[t2];
                if (denom == 0) continue;
                double contrib = (neigh[i].weight * neigh[j].weight) / denom;

                long long key = ((long long)t1 << 32) | (unsigned)t2;
                local.push_back({key, contrib});
            }
        }
    }

    // Combine all local vectors
    std::vector<PairEntry> all_pairs;
    size_t total_size = 0;
    for (auto& v : thread_pairs)
        total_size += v.size();
    all_pairs.reserve(total_size);

    for (auto& v : thread_pairs)
        all_pairs.insert(all_pairs.end(), v.begin(), v.end());

    // Step 4. Sort by key (parallel sort is used internally by libc++)
    std::sort(all_pairs.begin(), all_pairs.end(),
              [](const PairEntry& a, const PairEntry& b) { return a.key < b.key; });

    // Reduce identical keys
    std::unordered_map<long long, double> global_map;
    global_map.reserve(all_pairs.size() / 2);

    size_t i = 0;
    while (i < all_pairs.size()) {
        size_t j = i + 1;
        double sum = all_pairs[i].value;
        while (j < all_pairs.size() && all_pairs[j].key == all_pairs[i].key) {
            sum += all_pairs[j].value;
            ++j;
        }
        global_map[all_pairs[i].key] = sum;
        i = j;
    }

    return global_map;
}

void write_coocurr(const std::string output_path,
                   std::vector<std::string>& token_names,
                   std::unordered_map<long long, double>& map){
    std::ofstream out(output_path);
    if (!out) throw std::runtime_error("Cannot open " + output_path);
    for (auto& [key, w] : map) {
        int t1 = (int)(key >> 32);
        int t2 = (int)(key & 0xffffffff);
        out << token_names[t1] << "," << token_names[t2] << "," << w << "\n";
    }
}


int main(int argc, char* argv[]) {
    const std::string target_repo = argv[1];
    const std::string edges_path = target_repo + std::string("/edges.txt");
    const std::string files_path = target_repo + std::string("/files.csv");
    const std::string tokens_path = target_repo + std::string("/tokens.csv");
    const std::string output_path = target_repo + std::string("/cooccur.csv");

    try {
        // Load edges.txt → adjacency list (file → [(token, weight)])
        std::ifstream edges_in(edges_path);
        if (!edges_in) throw std::runtime_error("Cannot open " + edges_path);

        int max_file_id = -1, max_token_id = -1;
        {
            std::string line;
            while (std::getline(edges_in, line)) {
                if (line.empty()) continue;
                std::istringstream iss(line);
                int f, t; double w;
                if (!(iss >> f >> t >> w)) continue;
                max_file_id = std::max(max_file_id, f);
                max_token_id = std::max(max_token_id, t);
            }
        }
        edges_in.clear();
        edges_in.seekg(0, std::ios::beg);

        std::vector<std::vector<TokenEdge>> file_to_tokens(max_file_id + 1);
        {
            std::string line;
            while (std::getline(edges_in, line)) {
                if (line.empty()) continue;
                std::istringstream iss(line);
                int f, t; double w;
                if (!(iss >> f >> t >> w)) continue;
                file_to_tokens[f].push_back({t, w});
            }
        }
        std::cout << "Loaded " << (max_file_id + 1) << " files and "
                  << (max_token_id + 1) << " tokens.\n";

        // Step 2. Load token_id → token_name
        std::vector<std::string> token_names(max_token_id + 1);
        {
            std::ifstream in(tokens_path);
            if (!in) throw std::runtime_error("Cannot open " + tokens_path);
            std::string line;
            std::getline(in, line); // skip header
            while (std::getline(in, line)) {
                if (line.empty()) continue;
                std::istringstream iss(line);
                std::string tid_str, token;
                if (!std::getline(iss, tid_str, ',')) continue;
                if (!std::getline(iss, token)) continue;
                int tid = std::stoi(tid_str);
                if (tid >= 0 && tid <= max_token_id) token_names[tid] = token;
            }
        }

        double t_start_seq = omp_get_wtime();
        // std::unordered_map<long long, double> cooccur_map = bipartite_seq(max_token_id, max_file_id, file_to_tokens);
        double t_end_seq = omp_get_wtime();

        std::this_thread::sleep_for(std::chrono::seconds(2));  // rest 2 seconds

        double t_start_BT = omp_get_wtime();
        std::unordered_map<long long, double> global_map = bipartite_taversal(max_token_id, max_file_id, file_to_tokens);
        double t_end_BT = omp_get_wtime();

        std::this_thread::sleep_for(std::chrono::seconds(2));  // rest 2 seconds

        double t_start_map = omp_get_wtime();
        // std::vector<Pair> intermediate = map_reduce(max_token_id, max_file_id, file_to_tokens);
        double t_end_map = omp_get_wtime();

        // Write (token_string_1, token_string_2, normalized_weight)
        write_coocurr(output_path, token_names, global_map);

        std::cout << "Normalized co-occurrence written to " << output_path << "\n";
        std::cout << "\n[Sequential] time: " << (t_end_seq - t_start_seq) << " seconds\n";
        std::cout << "[Parallel   ] time: " << (t_end_BT - t_start_BT) << " seconds\n";
        std::cout << "[MapReduce  ] time: " << (t_end_map - t_start_map) << " seconds\n\n";

    } catch (const std::exception& ex) {
        std::cerr << "Error: " << ex.what() << "\n";
        return 1;
    }

    return 0;
}
