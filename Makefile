sim:
	g++ simulator.cc -o simulator

debug:
	clang++ -fsanitize=thread -g simulator.cc -o simulator

sim_omp:
	clang++ -DUSE_OPENMP -fopenmp -O2 simulator.cc -o simulator

sim_qft:
	g++ simulator_qft.cc -o simulator_qft

par_test_omp:
	clang++ -DUSE_OPENMP -fopenmp -O2 par_test.cpp -o prog

par_test_thread:
	clang++ -O2 par_test.cpp -o prog

clean:
	rm -f simulator debug simulator_qfts prog