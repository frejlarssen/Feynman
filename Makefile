# Compiler settings
CXX       = g++
MPICXX    = mpic++
CXXFLAGS  = -O2
OMPFLAGS  = -fopenmp
SANFLAGS  = -fsanitize=thread -g

# Targets
debug:
	$(CXX) $(SANFLAGS) apps/feynbitstr.cc -o simulator.x

bitstr_omp:
	$(CXX) -DUSE_OPENMP $(OMPFLAGS) $(CXXFLAGS) apps/bitstr.cc -o bitstr.x

sv_omp:
	$(CXX) -DUSE_OPENMP $(OMPFLAGS) $(CXXFLAGS) apps/sv.cc -o sv_omp.x

bitstr_mpi:
	$(MPICXX) -DUSE_MPI $(CXXFLAGS) apps/bitstr.cc -o bitstr_mpi.x

sv_batch_mpi:
	$(MPICXX) $(CXXFLAGS) -DUSE_OPENMP $(OMPFLAGS) apps/sv_batch.cc -o sv_batch_mpi.x

sv_scheduler_mpi:
	$(MPICXX) $(CXXFLAGS) -DUSE_OPENMP $(OMPFLAGS) apps/sv_scheduler.cc -o sv_scheduler_mpi.x

sv_prefetcher_mpi:
	$(MPICXX) $(CXXFLAGS) -DUSE_OPENMP $(OMPFLAGS) apps/sv_prefetcher.cc -o sv_prefetcher_mpi.x

sv_prefetcher_mpi_noOMP:
	$(MPICXX) $(CXXFLAGS) apps/sv_prefetcher.cc -o sv_prefetcher_mpi.x

sim_qft:
	g++ simulator_qft.cc -o sim_qft.x

clean:
	rm -f simulator.x bitstr sv_omp.x bitstr_mpi.x sv_mpi.x sim_qft.x
