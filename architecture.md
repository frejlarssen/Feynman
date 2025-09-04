# Architecture

## High level

1. Parse circuit. Identify internal wires.
2. For all history $h$:
    1. Multiply the amplitude of all gates, given the input and output determined by the histroy $h$.



## Input format

Tiny subset of QASM v3.

## Circuit representation

A circuit is a list of gates. A gate is defined by it's type, and internal wire (wire and position in that wire).

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

Represented with 2d array.

## Compute contribution

Compute contribution by multiplying amplitude $\alpha_G$ for all gates.

Start with $\alpha=1$

Update $\alpha \leftarrow \alpha \alpha_G$ etc.


Most of the time will be spent simulating a particular history -> Iterating over gates.

For `gate = {type, [{wire, internal_wire_in, control}]}`  we loop the qubits 

`q = {wire, internal_wire_in, control}`

and check if the internal wire `internal_wires[wire][internal_wire_in]` is 0 or 1, and if `control=False` we check if the output `internal_wires[wire][internal_wire_in+1]` is 0 or 1 (if it's a control qubit we know the output is the same as the input).

From this we pick the amplitude $\alpha_G$ from the `type` of the gate, and multiply.







