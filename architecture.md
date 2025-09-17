# Architecture

## High level

1. Parse circuit.
2. Build/analyse circuit.
3. For all history $h$:
    1. Multiply the amplitude of all gates, given the input and output determined by the histroy $h$.



## Input format

Subset of QASM v3. Follow conventions of QASM3.0 (qubit ordering etc).

I support gates such as `cccccz` with arbitrarily many controls. This is because I'm building a simulator that doesn't need to decompose with ancillas etc, which OpenQASM is targeting.

https://openqasm.com/language/standard_library.html#two-qubit-gates
In standard library, the first argument qubit is control and least significant.

In parsing we push back. wires[0] is the first argument, and least significant qubit of gate.

Gate should also have a similar argument list of qubits, so that evaluation know which qubit does what.
First qubit in a gate we stumble upon should not be first or last, but it depends on which parameter it is an argument to.

## Circuit representation / Prep stage

A circuit is an array of gates. A gate is defined by it's type, and internal wire (wire and position in that wire).

```
circuit:  list(gate)

gate:  {type, list({wire, internal_wire_in, global_index, control, at_input, at_output})}

QFT2 would be represented by this circuit: //TODO: Update
circuit =
[
    {H,[
        {0, 0, False}
       ]
    },
    {R2,[
         {1, 0, True},
         {0, 1, False}
        ]
    },
    {H,[
        {1, 0, False}
       ]
    },
    {SWAP,[
           {1, 1, False},
           {0, 2, False}
          ]
    }
]
```

We go through the gates from the output to input. This is so that we can keep track on which internal index we are at.
We go through the wires from $q_0$ to $q_{n-1}$, to keep it consistent with the way we go through the gates on wires.

Prep stage:
```
Parse file.
Divide into vectors, one for each wire. ParsedGate's end up in multiple wires.
For wire in wires:
    for ParsedGate on wire:
        keep track of internal wire. Store total internal wires per wire. Calculate global internal wire.
        OR: Keep track of global wire.
        Add to global list of Gate's, if not already added. Is sorted by id. Should only contain unique id's.
```

If they don't change 0/1 (control, Phase), they don't introduce a new internal wire.

Amplitude amplification with n=4, it=3 gives about 60 internal wires when only joining over non-switching.
When joining over all classical, it would be one internal wire for each of the 4+3*8=28 H-gates.
AA is nice to show that joining over classical helps, but for Feynman to be good we need less H-gates.
Time is exponential to depth, unlike Schrödinger method or Feynman for QFT.

Adder is classical -> Should be much better on Feynman than Schrödinger (but no quantum advantage).
Different kinds. Input + hard coded or input + input. For quantum walk we only need to add or subtract one.

Quantum walk: One H gate and some adder or similar (deterministic routine?) to implement the step. Maybe interesting mix of H-gates and deterministic. And it has applications?
https://quantumai.google/cirq/experiments/quantum_walks



### Join histories over deterministic gates
Phase, control, swap, cnot does not introduce new histories. (Phase is "classical" in this sense.)
But SWAP/CNOT etc introduces internal wire in some way (since 0/1 can shift). How to solve this without splitting the history? (CNOT can partially utalize the control, so SWAP is a cleaner example.)
An "internal wire" really sounds like it should be one value. So we need to revise the $H=2^{internal\_wires}$ formula.
We can differ between "internal wire" and "internal path". Where "internal path" is a set of internal wires, such that if we know the value of the first internal wire, we know the value of the last one.

How do we represent a history of internal histories? Assignment of 0/1 to the first internal wire of each internal path?

Can an "internal path" span multiple global wires?
* SWAP for example. The optimal is to recognize that the internal wire at output q0 only depends on the input of q1. Should I do these optimizations for all gates?
* One step worse is to only recognize that the SWAP is a classical gate, and that the two outputs depend on the two inputs somehow. In that case we would compute not only contribution when we simulate, but also actual paths (0/1s), instead of trying all histories.
* The simplest would be to not recognize that SWAP is something special. (As described above.) I could start with this to benchmark against.



We sometimes have H in the beginning and then only deterministic gates (QFT and arithmetic on superposition).
In these cases it would help alot (reduce to a single history) to also have backwards propagation from a selected output. This shouldn't be more difficult than forward.

Where can we store calculated 0/1:s? Not in the history, since they don't fit.
Maybe in the gates themselves.

New terminology: Input/output bitstrings constitute natural sources. We also need "induced sources". They are set by the history.
We need to keep track of which qubits are *reached* by natural and induced sources.

Change `at_input` and `at_output` to `induced_input` and `induced_output`, which is true if the value is decided by a series of deterministic gates, given a history. Initialize all of them to `false`.
They also have two booleans `input`and `output` which should be set later for each history.
If they are true, it means that they can be decided given a history, by propagating either forwards or backwards.

We need to look at all wires connected to a gate to know if a qubit should be `induced_output` or not.
How long time can the "compilation" phase take?
1. Set references `next` and `prev` of each `GateQubit` when creating them wire by wire.
2. Pass once time-forward and once time-backward. A "fake run" similar to when we run, but instead fo setting `input` and `output` we set `induced_input` and `induced_output`. The "fake run" can later be refined to make difference of different deterministic gates. A swap is deterministic on output 0 if it is deterministic on input 1 etc.

   Problem: Some induced sources might make others unnecessary! It matters for efficiency which order we set them.
3. Go wire by wire and count and name induction points (similar to the internal wires now).


How to store circuit?
When we run we want one time sorted vector of `Gate` to iterate.
When we run we also want to send the output of a deterministic `GateQubit` to the input of the next one on the same wire. We want this to be fast (no looping) since it happens for each history.

Either: One time-sorted vector of `Gate`. Each `GateQubit` has a reference to the next `GateQubit` on the same wire. One dereference for each `GateQubit`.
Or: Loop through a vector of references to `Gate`. One vector for each wire, where the `GateQubits` are stored. Would need two dereferences?




## Loop through histories

For each history we go through all gates by id ("time"). For each output qubit of the gate, we need to set the output of this one to the input of the next qubit on the same wire.
Either, we can have `wires` which is vectors of references to `GateQubit`s. Every GateQubit keeps track of where it is on the wire, and can by a dereference update the input of the next one. For each history, we do this once forwards, and once backwards. In the last one of them, or in a new pass, we calculate the contribution.

Loop through all histories (assignments 0/1 to all intenal wires).

A history: An assignment 0/1 of all pairs `(wire, internal_wire)`.

Each history is a 2d array of 0/1, which we can represent as a binary number, an `int history`.

We don't want input or output to be part of the histories. We want the histories to be of no relevance to the user so that they can be chosen with Monte Carlo.

When $h$ increment, we want the deepest internal wires to change first (feels more natural wrt depth first search/checkpointing etc). That is, the rightmost internal wires must be the LSB. This was the "binary value" of each wire can also be read intuitively.

## Compute contribution

Compute contribution by multiplying amplitude $\alpha_G$ for all gates in global list (same order as input file).

Start with $\alpha=1$

Update $\alpha \leftarrow \alpha \alpha_G$ etc.


Most of the time will be spent simulating a particular history -> Iterating over gates.

For `gate = {type, [{wire, internal_wire_in, control}]}`  we loop the qubits 

`q = {wire, internal_wire_in, control}`

and check if the internal wire `internal_wires[wire][internal_wire_in]` is 0 or 1, and if `control=False` we check if the output `internal_wires[wire][internal_wire_in+1]` is 0 or 1 (if it's a control qubit we know the output is the same as the input).

From this we pick the amplitude $\alpha_G$ from the `type` of the gate, and multiply.




## Same internal wire after PHASE:
Only one internal wire per qubit (between H and SWAP). Loop over $2^n$ histories. A history represents the value of the internal wire after H.

For each history:
Go through all gates, control is given by input bitstring. Rotate if needed.
Each history goes through $\mathcal{O}(n^2)$ gates


Total complexity: $2^n * \mathcal{O}(n^2) = \mathcal{O}(N* log^2(N))$


## Backwards SWAP
If outuput is given, we can perform the swap of the output. That should give the values (0/1) of the internal wires after the H-gates. Now we only need to try this single history.

If output bitstring is given, we can compute amplitude of that bitstring in $\mathcal{O}(n^2) = \mathcal{O}(log^2(N))$.

