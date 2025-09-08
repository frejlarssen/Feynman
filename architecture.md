# Architecture

## High level

1. Parse input bitstring.
2. Construct circuit of the size NUM_QUBITS, with structs and fixed size arrays.
3. For all history $h$:
    1. Multiply the amplitude of all gates, given the input and output determined by the histroy $h$.



## Input format

Tiny subset of QASM v3.

## Circuit representation

A circuit is an array of gates. A gate is defined by it's type, and internal wire (wire and position in that wire).

```
circuit:  list(gate)

gate:  {type, list({wire, internal_wire_in, control})}

QFT2 would be represented by this circuit:
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

## Loop through histories

Loop through all histories (assignments 0/1 to all intenal wires).

A history: An assignment 0/1 of all pairs `(wire, internal_wire)`.

Each history is a 2d array of 0/1, which we can represent as a binary number, an `int history`.

We don't want input or output to be part of the histories. We want the histories to be of no relevance to the user so that they can be chosen with Monte Carlo.

When $h$ increment, we want the deepest internal wires to change first (feels more natural wrt depth first search/checkpointing etc). That is, the rightmost internal wires must be the LSB. This was the "binary value" of each wire can also be read intuitively.

## Compute contribution

Compute contribution by multiplying amplitude $\alpha_G$ for all gates.

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

