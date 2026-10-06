Load heatwave
=============

Feel your machine working: when CPU load climbs, heat shimmer rises from the bottom of the terminal and the glow turns from orange to angry red.

Reads system load every two seconds (Linux ``/proc/loadavg``, ``os.getloadavg()`` elsewhere). The shimmer starts above 70% load per core and costs nothing while the machine is cool.

Install it from kitty's command palette with **Install bundled plugin**, then
**Review and enable**. Requested capabilities: shaders, timers.

Original code written for kitty's plugin API, distributed under GPL-3.0-or-later.
