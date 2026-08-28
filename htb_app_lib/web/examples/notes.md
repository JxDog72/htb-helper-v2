154.57.164.73:31580
154.57.164.65:32188
154.57.164.77:31697

# HTB Breach Challenge Description
Our relentless search led us to a secure testing site, a hub for concocting chemicals used in planet terraforming. Given its critical nature, a unique door system segregates the entire facility, allowing only a single door to open before a decontamination process ensues. Currently, the control sensors seem to be inoperative, keeping the system idle. Intriguingly, someone seems to have hardwired the sensor inputs to the output coils. Perhaps, this might be our entry point into the building.

### Instructions TXT file:
1. The door order that must be achieved to successfully allow the team to infiltrate the building is: [door_3, door_0, door_4, door_1, door_2] and must be sequential.
2. The coils for the doors have restricted access on the Modbus network and can not be written.
3. The sensors are hardwired to coils, thus driving the coil will result in the sensor signal being altered.
4. SYSTEM REST: Upon mission completion, the system will reset after approximately two minutes.
5. FLAG: the flag will be available on the holding registers starting at address 4 upon completion of the mission.

#### Workflow:
[08:40] Connected to ParrotOs
[08:47] Setting up client.py and file structure
[08:51] Reviewing the given txt & .st instructions file
	- holding registers starting at address 4 == Flag
	- Sys will reset after completion in 2 minutes
	- Order is [door_3, door_0, door_4, door_1, door_2] -> must be sequential
[08:58] pip install umodbus
[09:02] simple read_coils in client.py to confirm connection
[09:09] Further understanding of the instructions/st file before logging
	- 5 Doors (0-4)
	- From the door_control_subsystem.st information file   
	- Door_0 AT %Q4.0 : BOOL := 0; // Restrict write access via Modbus
    Door_1 AT %Q4.1 : BOOL := 0; // Restrict write access via Modbus
    Door_2 AT %Q4.2 : BOOL := 0; // Restrict write access via Modbus
    Door_3 AT %Q4.3 : BOOL := 0; // Restrict write access via Modbus
    Door_4 AT %Q4.4 : BOOL := 0; // Restrict write access via Modbus
    - specifies an<mark style="background: #FFB86CA6;"> 8-bit word</mark> size for modbus addresses, so:
	    - Door_0 = 4 * 8 + 0 = 32; Door_1 = 4 * 8 + 1 = 33
	    - 32 -> 36; 
	- But the control file/instructions mention these doors can not be written too...
[09:14] Lets look at the sensors in the .st file
[09:37] After reviewing the door_control_subsystem.st file in depth, I can see that we obviously can not write directly to the Doors(0-4), but the file tells us the sensors combinations(on/off) for each door (0-4)
	- So I need to figure out how to get the PLC's timers open the door by writing down each sensor combination for the doors (in the py client file I presume)
	- Instructions give us the order the sensors must open the doors to get the flag: 3->0->4->1->2; then read the flag from registry 4
[09:49]	- (starting_address=4 should give us the start of the HTB{flag...} if successful)
[09:50] Lets start logging and read the 5 door coils we can not write too from Modbus. 
[10:13] Restarting connection, server went wonky. Starting logging (original logs were just filled with the server not connecting due to the HTB server not responding anymore; new ip:port)
[10:24] have to step away to help neighbor, ran pyFile with 5 false readings(0,0,0,0,0)
[10:26] connected for 1.3 hours.
[02:13] back at pc, looking into the sensors_0-14 now.
 - https://content.helpme-codesys.com/en/CODESYS%20Development%20System/_cds_operands_addresses.html
	 - tells me that Q is an output memory area and X is a single bit
	 - these sensors for ex. sensor_1 AT %QX8.1
		 - would mean %QX8.1  is the mem_address of the plc sensor.
		 - 8 bytes, 1 bit = 8.1, (8,1) = 8 * 8 + 1 = 65 address for sensor_1
		- def foo(var):
			- byte, bit = var
			- return (byte * 8) + bit ; same math as above for the sensor_address
		
[02:42] Laying out which sensors need to be on for the doors 3-0-4-1->2
- door_order = [(3, True), (0, True), (4, True), (1, True), (2, True)]
- 35, 32, 36, 33, 34 -> coil address order
- Door sensor logic:

| Door Sensors | Value 1 = on, 0 = off             |
| ------------ | --------------------------------- |
| Door 3       | 5 seconds                         |
| Sensor_13    | 1                                 |
| Sensor_12    | 1                                 |
| Sensor_11    | 0                                 |
| Sensor_10    | 1                                 |
| Sys_active   | 1                                 |
| Door 0       | 8 seconds                         |
| Sensor 4     | 1                                 |
| Sensor_2     | 0                                 |
| Sensor_1     | 1                                 |
| Sensor_0     | 1                                 |
| Sys_active   | 1                                 |
| Door 4       | 8 seconds                         |
| Sensor_14    | 1                                 |
| Sensor_13    | 1                                 |
| Sensor_12    | 1                                 |
| Sensor_10    | 1                                 |
| Sensor_11    | 1, Included to not trigger door 3 |
| Sys_active   | 1                                 |
| Door 1       | 5 seconds                         |
| Sensor_7     | 1                                 |
| Sensor_6     | 0                                 |
| Sensor_5     | 1                                 |
| Sensor_0     | 1                                 |
| Sys_active   | 1                                 |
| Door 2       | 8 seconds                         |
| Sensor_11    | 1                                 |
| Sensor_7     | 0                                 |
| Sensor_10    | 1                                 |
| Sensor_5     | 1                                 |
| Sys_active   | 1                                 |
- We must wait for each door to finish opening before moving on to prevent conflicts, like with sensor_11 and door 3 and 4. 
[03:17] So we need to:
1. activate these sensors in order
2. include the sleep time,
3. and then reset the sensors to false 
4. loop to activate the ones for the next door..
5. read reg values at addr:4
def foo(sensor, value):
- sensor_address = ()
- 
[8, 0] sensor_0 = 64
[8, 1] sensor_1 = 65
[8, 2] sensor_2 = 66 
[8, 3] sensor_3 = 67 
[8, 4] sensor_4 = 68
[37, 0] sensor_5 = 296
[37, 1] sensor_6 = 297 
[37, 2] sensor_7 = 298
[37, 3] sensor_8 = 299
[37, 4] sensor_9 = 300
[52, 0] sensor_10 = 416
[52, 6] sensor_11 = 422
[16, 6] sensor_12 = 134
[16, 7] sensor_13 = 135
[16, 0] sensor_14 = 128
[75, 2] system_active = 602
- So now when we write to the sensor, we can just do 
- def write_sensor(sensor_address, value): 
	- command = tcp.write_single_coil( slave_id=1, address= sensor_address, value=1(for true))
	- tcp.send_message(command, sock)
- write_sensor(sensor_0, True) == write_sensor(64, True)

- We can predefine each door sequence: 
door_sensors = {
	door_0: [
	(sensor_4, True),(sensor_2, False),(sensor_1, True),(sensor_0, True),
	] 
     door_1: [
     (sensor_7, True),(sensor_6, False),(sensor_5, True),(sensor_0, True),
     ]
     door_2: [ 
     (sensor_11, True),(sensor_7, False),(sensor_10, True),(sensor_5, True),
     ]
    door_3: [
    (sensor_13, True),(sensor_12, True),(sensor_11, False),(sensor_10, True),
      ]
    door_4: [ 
    (sensor_14, True),(sensor_13, True),(sensor_12, True),(sensor_10, True),(sensor_11,True),    
    ] 
     
 }
 or like 
 door_order = [
    {
        "door": 3,
        "time": 5,
        "sensors": {
            "sensor_13": 1,
            "sensor_12": 1,
            "sensor_11": 0,
            "sensor_10": 1,
            "system_active": 1,
        }
    },
    {
        "door": 0,
        "time": 8,
        "sensors": {
            "sensor_4": 1,
            "sensor_2": 0,
            "sensor_1": 1,
            "sensor_0": 1,
            "system_active": 1,
        }
    },
    # ...
]
 [03:30] for the sleep(time), we can do if the door is 0,2, or 4 then sleep for 8-9 seconds, otherwise sleep for 5 seconds before continuing. 
[03:52] Thinking about how we can read the flag once we get there, the address is given as "4", so I assume just read the holding registers: 
- command = tcp.read_holding_registers(slave_id=1,starting_address=4,qauntity=100)
- register_values = tcp.send_message(command, sock)

[next day 04:00pm] Trying to decide how to make the code more dynamic and not use repetitive statements opening each door. 
[05:02] Major milestone, was able to open door 3 and door 4!
[05:27] Included a dictionary with the door_rules and sensor values.
- Need to include a reset() function since some doors like 3 and 4 will conflict. 
[06:04] Have made a function to open all the doors in one go but having difficulties. 
[08:10] Back on the pc from meeting. 
[08:45] Went back to hard coding method to first solve, so far have 3 doors open at once. 
[11:05] Flag found after altering the python logic to keep certain doors open.
