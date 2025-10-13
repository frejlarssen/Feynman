# Monte carlo

Argumnet -f to specify fraction of histories to simulate.

Experiment to see how this relate to fidelity for different circuits.


## How to choose which histories?
We can for example choose to simulate $f$ out of the c_2-histories and all over c_1 and c_2. If we choose another strategy, we need to take the strategy and $f$ into account when doing the autotuning.

We randomize which c_2-histories to simulate.

## Normalize
If we have $f=0.5$ and we get the summed amplitude $\alpha_f = 0.25 + 0.25i$, the full sum should be $\alpha = \frac{\alpha_f}{f} = 0.5 + 0.5i$.



## How to implement?
Either: vector of all histories $f\cdot(1 << A_2)$ we want to loop through.
Randomize exactly $f\cdot(1 << A_2)$ histories in the span $[0,(1 << A_2))$.
Do they need to be unique? If not, f=1 wouldn't be exact.


Or: Iterate as now. For each history, continue with probability $1-f$.
Would be unique histories. Wouldn't be exactly $f$ histories we simulate. But shuold be close if (1<< A_2) is big. f=1 would be exact.


