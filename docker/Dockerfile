FROM ubuntu:22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ python3 python3-pip libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/hpc-grid
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY . .

RUN g++ -O2 -std=c++17 -fopenmp -Wall kernels/omp_kernels.cpp -o bin/omp_kernels \
 && chmod +x bin/omp_kernels

ENV PYTHONPATH=/opt/hpc-grid
ENTRYPOINT ["python3", "-m", "worker"]
CMD ["--master", "127.0.0.1:9100", "--kind", "cloud", "--auto-consent"]
