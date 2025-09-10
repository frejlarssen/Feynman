# Architecture

## High level

1. Construct circuit.
2. Parse input/output bitstring.
3. For all history $h$:
    1. Multiply the amplitude of all gates, given the input and output determined by the histroy $h$.



## Input format

Subset of QASM v3. Follow conventions of QASM3.0 (qubit ordering etc).

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


### Possible improvement
Phase, control, swap, cnot does not introduce new histories. (Phase is "classical" in this sense.)
But SWAP/CNOT etc introduces internal wire in some way (since 0/1 can shift). How to solve this without splitting the history? (CNOT can partially utalize the control, so SWAP is a cleaner example.)
An "internal wire" really sounds like it should be one value. So we need to revise the $H=2^{internal\_wires}$ formula.
We can differ between "internal wire" and "internal path". Where "internal path" is a set of internal wires, such that if we know the value of the first internal wire, we know the value of the last one.

How do we represent a history of internal histories? Assignment of 0/1 to the first internal wire of each internal path?

Can an "internal path" span multiple global wires?
* SWAP for example. The optimal is to recognize that the internal wire at output q0 only depends on the input of q1. Should I do these optimizations for all gates?
* One step worse is to only recognize that the SWAP is a classical gate, and that the two outputs depend on the two inputs somehow. In that case we would compute not only contribution when we simulate, but also actual paths (0/1s), instead of trying all histories.
* The simplest would be to not recognize that SWAP is something special. (As described above.) I could start with this to benchmark against.



## Loop through histories

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

