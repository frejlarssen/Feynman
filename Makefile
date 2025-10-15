debug:
	clang++ -fsanitize=thread -g apps/feynbitstr.cc -o simulator

bitstr_omp:
	clang++ -DUSE_OPENMP -fopenmp -O2 apps/bitstr.cc -o bitstr

sv_omp:
	clang++ -DUSE_OPENMP -fopenmp -O2 apps/sv.cc -o sv

sim_qft:
	g++ simulator_qft.cc -o simulator_qft

clean:
	rm -f simulator debug simulator_qfts