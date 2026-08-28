# HTB Challenge: Breach - ICS - Medium
## Executive Summary
A secure chemical testing site has 5 containment doors set up so that only one door can open at a time during the decontamination process. We need to open the doors in a specific order, but we cannot directly write to the door coils. Instead, the input sensors for the door opening logic are hardwired, altering the sensors is how we can open the doors. We are given a layout showing which sensors each door requires to be opened.
## Scope
Breach, 154.57.164.77:31697, 08/17/2026 - 08/20/2026
## Methodology
We are given three starter files: 'client.py', 'Instructions.txt', and 'door_control_subsystem. st'. After reviewing those, my general approach to this challenge was to first read values from the doors and sensors, then try each door/sensor one at a time.To determine the correct addresses, I spent several hours deciphering the provided door_control_sybsystem.st file.
Once I had all the addresses, I began writing to the sensors for door 3 until I was able to open it. Then I implemented the logic to open each door according to its timing and sensors.
## Findings
Vulnerability: System allows an attacker to manipulate sensor inputs that can satisfy the requirements to open restricted doors.
## Attack Narrative
First, I connected and ran the provided client.py file to confirm the connection. Then I examined what the door_control_subsystem.st file was telling me for each sensor and door. It clearly states that the doors cannot be written to, but the sensors can, so I needed to determine their actual addresses to write to them. That is where the layout file came in handy; it lists the addresses, but we have to convert them, %QX8.1.

The Q is for output memory and X is for a single bit. For example, sensor_1 at %QX8.1 = 8 * 8 + 1 = 65 (sensor_1). After calculating the addresses for the sensors and doors, I started reading their states and attempting to write to them using: 
tcp.read_coils(id, addr, quantity) 
tcp.write_single_coil(id, addr, value)

After successfully opening 1 door, I attempted to open the other doors in order (3->0->4->1->2), but one would open while the last one closed... Each door requires different sensors to be open and closed, and some conflict with other doors.

Take door 1 and 2 for example:
door_1: [ (sensor_7, True),(sensor_6, False),(sensor_5, True),(sensor_0, True), ] 
door_2: [ (sensor_11, True),(sensor_7, False),(sensor_10, True),(sensor_5, True), ] 
As you can see, they both have different values for sensor_7. So I made lists for each door and what their requirements are. I was able to keep 3 doors open at one point, but they would close as soon as I tried the next door.

I then went back to study the door_control_subsystem.st file some more and found the exact timings for each door. Even doors had to be held for 8 seconds, while the odd doors required 5 seconds.

Once I was able to get the timing to make the doors stay open, the flag was revealed within the 2-minute reset timer. I read the values from the 5 doors, and the flag was revealed in an ASCII list with: command = tcp.read_holding_registers(1, 4, 100) and then printing the response.
## Remediation
Sensor input validation: If the system detects a sensor anomaly that should be impossible, such as a conflict with other hardwired sensors, it should raise a flag, halt for review, and implement logic updates to the system based on the findings. The system should not trust any sensor input without verifying its authenticity.
## Conclusion
This was a very challenging lab that required hours of research to understand how to bypass the software-enforced PLC logic that prevented direct writing to the door coils. This challenge highlights a major flaw in ICS security designs: Simply implementing hardwired logic to prevent access is not good enough.