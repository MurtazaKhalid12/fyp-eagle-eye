#include <iostream>
using namespace std;
#include <string>

int main() {
    int* p = new int; // Allocate memory for an integer
    *p = 42; // Assign a value to the allocated memory
    cout << "Value: " << *p << endl; // Output the value
    delete p; // Deallocate the memory
    return 0;
}