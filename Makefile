# Compiler settings
CXX       = g++
MPICXX    = mpic++
CXXFLAGS  = -O2
OMPFLAGS  = -fopenmp
SANFLAGS  = -fsanitize=thread -g

# Targets
debug:
	$(CXX) $(SANFLAGS) apps/feynbitstr.cpp -o simulator.x

bitstr_omp:
	$(CXX) -DUSE_OPENMP $(OMPFLAGS) $(CXXFLAGS) apps/bitstr.cpp -o bitstr.x

sv_omp:
	$(CXX) -DUSE_OPENMP $(OMPFLAGS) $(CXXFLAGS) apps/sv.cpp -o sv_omp.x

bitstr_mpi:
	$(MPICXX) -DUSE_MPI $(CXXFLAGS) apps/bitstr.cpp -o bitstr_mpi.x

sv_batch_mpi:
	$(MPICXX) $(CXXFLAGS) -DUSE_OPENMP $(OMPFLAGS) apps/sv_batch.cpp -o sv_batch_mpi.x

sv_scheduler_mpi:
	$(MPICXX) $(CXXFLAGS) -DUSE_OPENMP $(OMPFLAGS) apps/sv_scheduler.cpp -o sv_scheduler_mpi.x

sv_prefetcher_mpi:
	$(MPICXX) $(CXXFLAGS) -DUSE_OPENMP $(OMPFLAGS) apps/sv_prefetcher.cpp -o sv_prefetcher_mpi.x

sv_prefetcher_mpi_subsetbitstrings:
	$(MPICXX) $(CXXFLAGS) -DUSE_OPENMP -DUSE_SUBSET_OUTBITSTRINGS $(OMPFLAGS) apps/sv_prefetcher.cpp -o sv_prefetcher_subset_mpi.x

sv_prefetcher_mpi_subsetbitstrings_noomp:
	$(MPICXX) $(CXXFLAGS) -DUSE_SUBSET_OUTBITSTRINGS apps/sv_prefetcher.cpp -o sv_prefetcher_subset_mpi.x

sim_qft:
	g++ simulator_qft.cpp -o sim_qft.x

clean:
	rm -f simulator.x bitstr sv_omp.x bitstr_mpi.x sv_batch_mpi.x sv_scheduler_mpi.x sv_prefetcher_mpi.x sv_prefetcher_subset_mpi.x sim_qft.x
