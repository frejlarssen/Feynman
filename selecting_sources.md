# Selecting sources of artificial determinism

Each history needs to be deterministic. That is, for a specific history we need to be able to decide a unique value $\in \{0,1\}$ for each wire. The input and output bitstrings constitute natural sources of determinism. H-gates require us to induce new sources of determinism, that are set at simulation time for each history. Where the sources are is decided in the analysis phase.

The number of histories are $2^{\# artificial\_sources}$.

We would therefore like to minimize the number of artificial sources.

Information only spread in the horizontal direction. Given that all inputs to a deterministic gate are *reached* by a source, the output is also reached. The reverse is also true, due to reversability of gates.
(TODO: An optimization would be to not be agnostic about gate type. For example, one output is reached if one input is reached to a swap. But the general ideas should be the same. Even if we are aware of swaps, we can't get information about what's happeing directly above or below.)

If the gate is nondeterministic (H-gate) we *might* induce a source at it's output. But it might be reached from the other direction.

A natural way to set artificial sources is to go through the circuit from left to right (L->R) (order given by the time/line nr of the input file) and keep track of reached wires.

We can also try both L->R and R->L and compare which is best. We denote this algorithm L<->R.

In Ex1, neither L->R or R->L is optimal to minimize the number of artificial sources. Therefore, L<->R would not find the optimal solution. (One optimal solution is to go L->R on wires $q_{2-3}$ and R->L on wires $q_{0-1}$. This gives two artificial sources.)

The following sections outline some ideas.

## Set intersection
Do both L->R and R->L. Check which wires were artificial in both of them. Doesn't work for Ex1. None were artificial in both.

Can we "Combine L->R and R->L some other way"?

## Wire Brute-force?
For each wire, check if it should be part of a L->R or R->L.
Does this cover all solutions? No, we could do both L-R and R->L for the same wire until the middle.

Does this cover the optimal solution?

## Gate Brute-force?
For each gate, check if it should be L->R or L->R.
$\mathcal{O}(2^G)$ analysis/"compile"-time. Is that ok?

## Translate to graph problem?
Or at least find a graph problem that can give inspiration to solving this one.


## Check if L<->R is optimal for some common circuits.

We neglect any prep. The user can simulate many basis states and add with weighted with amplitudes.

### QFT
L->R induces one source after each H-gate

R->L induces no sources.

R->L is optimal.

### Amplitude amplification
$n$ qubits and the mark has $k$ Not-gates on each side. $I$ iterations.

L->R induces one after each H-gate, except the last ones.

$\#_{artificial} = 2nI - n$.

R->L induces one left to each H-gate, except the ones that goes straight to control in the first iteration, because they are at natural source.

$\#_{artificial} = 2nI - (n-k)$

L->R is slightly better. And optimal (I think).

### Quantum Walk
L->R: One artificial for each H-gate.

R->L: One artificial for each H-gate except leftmost.

R->L optimal.

### Summary

L<->R is optimal strategy for QFT, iterative Amplitude Amplification and Quantum Walk.