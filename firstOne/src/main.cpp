#include <Arduino.h>

/*
  Blink

  Turns an LED on for one second, then off for one second, repeatedly.

  Most Arduinos have an on-board LED you can control. On the UNO, MEGA and ZERO
  it is attached to digital pin 13, on MKR1000 on pin 6. LED_BUILTIN is set to
  the correct LED pin independent of which board is used.
  If you want to know what pin the on-board LED is connected to on your Arduino
  model, check the Technical Specs of your board at:
  https://www.arduino.cc/en/Main/Products

  modified 8 May 2014
  by Scott Fitzgerald
  modified 2 Sep 2016
  by Arturo Guadalupi
  modified 8 Sep 2016
  by Colby Newman

  This example code is in the public domain.

  https://www.arduino.cc/en/Tutorial/BuiltInExamples/Blink
*/

/*
JH-D202X-R2/R4 Joystick Module Test

Basic code for monitoring the outputs of the joystick. 
*/
int xPin = A1;      // Use any analog input pin to read X-Axis pot
int yPin = A0;      // Use any analog input pin to read Y-Axis pot
int xPosition = 0;  // Variable to hold current X-Axis reading
int yPosition = 0;  // Variable to hold current Y-Axis reading
//===============================================================================
//  Initialization
//===============================================================================


// the setup function runs once when you press reset or power the board
void setup() {
  // initialize digital pin LED_BUILTIN as an output.
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(9600);
}

// the loop function runs over and over again forever
void loop() {
  digitalWrite(LED_BUILTIN, HIGH);  // turn the LED on (HIGH is the voltage level)
  delay(1000);                      // wait for a second
  digitalWrite(LED_BUILTIN, LOW);   // turn the LED off by making the voltage LOW
  delay(1000);                      // wait for a second

  
  xPosition = analogRead(xPin);         // Read the current state of both controls
  yPosition = analogRead(yPin);
  
  Serial.print("X: ");                  // Print state to Serial Monitor window
  Serial.print(xPosition);
  Serial.print(" | Y: ");
  Serial.println(yPosition);

  delay(250);    // add some delay between reads. 
}
