# Quick Start
## Setup
Clone the GitHub repo we want to process under ```/repo```.

Clone ```json``` repo to the same level as ```repo_reader.cpp```, ```index2bipartite.cpp```:
```
git clone https://github.com/nlohmann/json.git
```


## Compile and Run
Build CMake using default C++ compiler:
```
mkdir -p build && cd build
cmake ..
cmake --build .
```
In ```/build```:

**Build index for a given repo:**
```
./repo_reader ../repos/<target repo>
```
The resulting index will be saved as ```<target repo>.json``` under ```/index```.


**Build bipartite graph for a given index:**
```
./index2bipartite ../index/<target index>.json
```
Three files ```edges.txt```, ```files.csv```, and ```tokens.csv``` will be stored under ```/graph/<target index>```
- ```edges.txt```: ```(file_id, token_id, weight)```, where ```weight``` represents the number of occurances of ```token_id``` in ```file_id```.
- ```files.csv```: mapping ```file_id``` -> ```repo, file```.
- ```tokens.csv```: mapping ```token_id``` -> ```token_string```.

**Calculate Cooccurrences:**
```
./cooccur ../graph/<target repo>/
```
A new file ```cooccur.csv``` will be stored under ```../graph/<target repo>/```, containing the cooccurrences of all token pairs in the repo.

## Rebuild CMake
```
cmake --build .
```

## Clean and Rebuild CMake
```
rm -rf build
mkdir build
cd build
cmake ..
cmake --build .
```