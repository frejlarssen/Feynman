simulator:
	g++ simulator.cc -o simulator

debug:
	clang++ -fsanitize=thread -g simulator.cc -o simulator

simulator_qft:
	g++ simulator_qft.cc -o simulator_qft

clean:
	rm -f simulator debug simulator_qfts 