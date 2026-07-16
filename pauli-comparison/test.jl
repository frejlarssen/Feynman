using PauliPropagation

nqubits = 32
observable = PauliString(nqubits, :Z, 16)
println(observable)
