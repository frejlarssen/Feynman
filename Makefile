simulator:
	g++ -fopenmp simulator.cc -o simulator

simulator_qft:
	g++ simulator_qft.cc -o simulator_qft

clean:
	rm -f simulator simulator_qfts