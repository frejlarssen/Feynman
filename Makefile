# Compiler settings
CXX       = clang++
MPICXX    = mpic++
CXXFLAGS  = -O2
OMPFLAGS  = -fopenmp
SANFLAGS  = -fsanitize=thread -g

# Targets
debug:
	$(CXX) $(SANFLAGS) apps/feynbitstr.cc -o simulator

bitstr_omp:
	$(CXX) -DUSE_OPENMP $(OMPFLAGS) $(CXXFLAGS) apps/bitstr.cc -o bitstr

sv_omp:
	$(CXX) -DUSE_OPENMP $(OMPFLAGS) $(CXXFLAGS) apps/sv.cc -o sv_omp

bitstr_mpi:
	$(MPICXX) -DUSE_MPI $(CXXFLAGS) apps/bitstr.cc -o bitstr_mpi

sv_mpi:
	$(MPICXX) -DUSE_MPI $(CXXFLAGS) apps/sv.cc -o sv_mpi

sim_qft:
	g++ simulator_qft.cc -o sim_qft

clean:
	rm -f simulator bitstr sv simulator_qft bitstr_mpi sv_mpi sim_qft
