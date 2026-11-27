CXX ?= g++
CXXFLAGS ?= -O2 -std=c++17 -fopenmp -Wall -Wextra
OUT_DIR ?= ../bin
TARGET = $(OUT_DIR)/omp_kernels

ifeq ($(OS),Windows_NT)
  EXE = $(TARGET).exe
else
  EXE = $(TARGET)
endif

.PHONY: all clean selftest

all: $(EXE)

$(OUT_DIR):
	mkdir -p $(OUT_DIR)

$(EXE): omp_kernels.cpp | $(OUT_DIR)
	$(CXX) $(CXXFLAGS) $< -o $@

selftest: $(EXE)
	$(EXE) selftest

clean:
	rm -f $(EXE) $(TARGET).exe
