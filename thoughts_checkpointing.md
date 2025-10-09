3 chunks or arbitarary?
Maybe I could do arbitrary, but it would maybe be more complicated to combine with portability, MPI etc.
I'll start with 3 chunks.


Each chunk has it's own input, output and artificial sources.
The INPUT iw's of one is the OUTPUT's of the next.



1. Refactor to make parsing it's own struct. (join-deterministic)

New branch from join-deterministic: join-deterministic-cp

2. Refactor to make those atributes that later will be per-chunk nonstatic (checkpointing).


3. 3 chunks.

We know that: Simulation would have `right_to_left_artificial` per-chunk. Therefore, it is natural that `right_to_left_natural` is per-chunk and `right_to_left_fake` is per-chunk.
But `build_circuit` builds the whole circuit, and the 3 chunks, so that the InternalWires are shared between the chunks. It calls `right_to_left_fake` for each chunk.

Same STATUS-system as for whole circuit.
`right_to_left_natural` would be called for each chunk, but we don't need to set INPUT because they are already set and marked REACHED/ARTIFICIAL from the simulation of the previous chunk. But in wrong history-spaces...

When we start R->L_natural of C1, we need to know for a specific gate if it's right wire has history space from C0 or C1, to know if it's set or not.
We need `int iw->starts_in_chunk`.


Standardized output for debugging:
Contribution from --0 means: Only gates in C2 have run. 
Contribution from AA0 means: History C0 have completed, with all it's "subhistories".


Input and output has it's own history space (with only one history). iw with chunk NUM_CHUNKS is input and with NUM_CHUNKS+1 is output.



In last version the number of histories for INPUT was same as any other internal wire. Now it's only one.



Problem: History 0 of an internal wire in chunk 1 needs to be set for --0, but then not set for --1.
We can reset. But for multithreading over Chunk 2 --X we need both at the same time.

Let $|H_c|$ be number of histories over chunk $c$.

* For multithreading over chunk 2, we need to store $|H_2|$ values for each internal wire, no matter where it's starting!
We reset this every time we start a new history over chunk 1 and 0.

* For multithreading over only chunk 1, we need to store $|H_1|$ values for each internal wire starting in chunk 1 or chunk 0 and 1 for those starting in chunk 2.

* For multithreading over chunk 2 and 1, we need to store $|H_2||H_1|$ values for each iw starting in chunk 1 or 0, and $|H_2|$ for those starting in chunk 2.

Let's start with multithreading only over chunk 2, to save memory and implementation complexity.

Input and output only needs 1 history.

We need to know which iw's to reset. Each chunk stores a vector of iw's starting in that chunk.



right_to_left_natural needs to operate per-thread for chunk 0 and 1.



We need to reset the wires in chunk 1 before doing artificial pass for a new history in chunk 1. But when we reset, we need to do a new natural_pass.
We could either:
* Store in STATUS which were REACHED_NATURAL and which were REACHED_ARTIFICIAL, and only reset those that were REACHED_ARTIFICIAL.
* Run natural_pass after each reset, just before artificial_pass.

_artificial iterates only deterministically breaking. But if it would have iterated all gates it could have catched more value-rejects. TODO: Investigate this trade-off later.



For now: Easy implementation with looping only deterministically breaking for propagating vals. Calc_contribution checks if activated etc.
TODO: Investigate performance of setting vals and then calculating contribution or doing all at once. And catching rejects early vs looping only deterministically breaking gates



## Testing
We want to test for all possible selections of -p and -r.
Run with -B first to check how many gates and artificial sources in each chunk.


## Autotuning of checkpointing


$G_c$ gates in chunk $c$. $T_{g}$ time for one gate application.

$T_c = G_c*T_{g}$ time for gates in chunk $c$ once.

$A_c$ number of artificial sources in chunk $c$.

$T_{tot} = A_2 (T_2 + A_1(T_1 + A_0 T_0))$

$T_{tot} = A_2 (G_2 + A_1(G_1 + A_0 G_0))T_{g}$


-p = $G_2$ depends on how many threads we have (and desired fidelity if we don't simulate all histories).

For analytical solution, we need some assumption of how $A_c$ depends on $G_c$. This is not a constant density for circuits like QFT, but might be for random circuits.

We can try all values of $G_1$ in linear time. Iterate build_circuit with different num_chunk1 and calculate $A_1(G_1 + A_0 G_0)$ for each selection.













TODO: Test structurally and fix remaining edge case bugs.