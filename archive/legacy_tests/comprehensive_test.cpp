#include <iostream>

using namespace std;

#define MAX_STUDENTS 5
#define BONUS_POINTS 10

// -----------------------------------------------------------------------------
// 1. Enum Definition
// -----------------------------------------------------------------------------
enum Subject {
    MATH = 1,
    SCIENCE = 2,
    COMPUTING = 3
};

// -----------------------------------------------------------------------------
// 2. Struct Definition
// -----------------------------------------------------------------------------
struct StudentStats {
    int id;
    int totalScore;
    char grade;
};

// -----------------------------------------------------------------------------
// 3. Namespace
// -----------------------------------------------------------------------------
namespace Analytics {
    int computeSquare(int val) {
        return val * val;
    }

    int clampScore(int score, int low, int high) {
        if (score < low) return low;
        if (score > high) return high;
        return score;
    }
}

// -----------------------------------------------------------------------------
// 4. Function Templates & Class Templates
// -----------------------------------------------------------------------------
template <typename T>
T findMax(T a, T b) {
    return (a > b) ? a : b;
}

template <typename T>
T findMin(T a, T b) {
    return (a < b) ? a : b;
}

// -----------------------------------------------------------------------------
// 5. Object-Oriented Hierarchy (Inheritance & Polymorphism)
// -----------------------------------------------------------------------------
class Participant {
protected:
    int id;

public:
    void setId(int newId) {
        this->id = newId;
    }

    int getId() {
        return this->id;
    }

    virtual int evaluate() {
        return 0;
    }
};

class Student : public Participant {
private:
    int midterm;
    int finalExam;

public:
    Student(int m, int f) {
        this->midterm = m;
        this->finalExam = f;
    }

    int evaluate() override {
        int avg = (this->midterm + this->finalExam) / 2;
        return avg;
    }
};

class GraduateStudent : public Participant {
private:
    int thesisScore;

public:
    GraduateStudent(int thesis) {
        this->thesisScore = thesis;
    }

    int evaluate() override {
        return this->thesisScore;
    }
};

// -----------------------------------------------------------------------------
// 6. Operator Overloading
// -----------------------------------------------------------------------------
class BonusCalculator {
public:
    int baseBonus;

    BonusCalculator(int b) {
        this->baseBonus = b;
    }

    int operator+(int extra) {
        return this->baseBonus + extra;
    }

    bool operator==(int target) {
        return this->baseBonus == target;
    }
};

// -----------------------------------------------------------------------------
// 7. Function Overloading & Recursion
// -----------------------------------------------------------------------------
int factorial(int n) {
    if (n <= 1) {
        return 1;
    }
    return n * factorial(n - 1);
}

int calculateGradePoints(int score) {
    return score / 10;
}

double calculateGradePoints(double gpa) {
    return gpa * 25.0;
}

// -----------------------------------------------------------------------------
// 8. Deliberately Unoptimized Code (For Demonstrating Optimizer Passes: -O1 / -O2)
// -----------------------------------------------------------------------------
int demonstrateOptimization() {
    // A. Unoptimized Arithmetic (Candidates for Constant Folding):
    // The optimizer computes this at compile time instead of emitting runtime MUL/DIV/ADD/SUB.
    int folded1 = 100 + (25 * 4) - (50 / 2); // 175
    int folded2 = 10 * 0;                    // 0 (Algebraic identity x * 0 = 0)
    int folded3 = folded1 + 0;               // 175 (Algebraic identity x + 0 = x)

    // B. Dead Branches (Candidates for Dead Code Elimination):
    // The optimizer detects constant conditions and prunes unreachable branches.
    int activeValue = 10;
    if (0) {
        // Dead Branch: Pruned completely by -O1 and -O2
        activeValue = 9999;
    } else {
        activeValue = activeValue + 5; // Taken
    }

    if (1) {
        // Always-True Condition: Unwrapped by optimizer
        activeValue = activeValue * 2; // 15 * 2 = 30
    }

    // C. Bounded Loop (Candidate for Loop Unrolling under -O2):
    // Loop overhead is removed by unrolling into flat sequential statements.
    int unrolledSum = 0;
    for (int k = 0; k < 3; k++) {
        unrolledSum = unrolledSum + 5; // 15
    }

    return activeValue + folded1 + folded2 + (folded3 - folded1) + unrolledSum; // 30 + 175 + 0 + 0 + 15 = 220

    // D. Unreachable Statements after Return (Pruned by Dead Code Elimination):
    int deadVar = 42;
    activeValue = deadVar + 100;
}

// -----------------------------------------------------------------------------
// MAIN PROGRAM: Comprehensive Compiler Test Suite
// -----------------------------------------------------------------------------
int main() {
    cout << "============================================================" << endl;
    cout << "       COMPREHENSIVE C++ COMPILER VERIFICATION SUITE       " << endl;
    cout << "============================================================" << endl;
    cout << endl;

    // Test 1: Arithmetic & Operator Precedence
    cout << "[TEST 1] Arithmetic & Operator Precedence:" << endl;
    int a = 15;
    int b = 4;
    int arithResult = a * 2 + (b * 3) / 2 - (a % b);
    cout << "  Expression 15*2 + (4*3)/2 - (15%4) = " << arithResult << endl;
    cout << endl;

    // Test 2: Pointers and References
    cout << "[TEST 2] Pointers & References:" << endl;
    int target = 50;
    int* ptr = &target;
    *ptr = 75;
    int& ref = target;
    ref = ref + 5;
    cout << "  Target value via pointer and reference: " << target << " (Expected: 80)" << endl;
    cout << endl;

    // Test 3: Arrays, For Loops, & Accumulation
    cout << "[TEST 3] Arrays & Loop Control Flow:" << endl;
    int scores[5];
    scores[0] = 88;
    scores[1] = 92;
    scores[2] = 79;
    scores[3] = 95;
    scores[4] = 84;

    int sum = 0;
    for (int i = 0; i < 5; i++) {
        sum = sum + scores[i];
    }
    int average = sum / 5;
    cout << "  Scores sum = " << sum << ", Average = " << average << endl;

    // While and Do-While loops
    int loopCounter = 0;
    int whileSum = 0;
    while (loopCounter < 4) {
        whileSum = whileSum + loopCounter;
        loopCounter = loopCounter + 1;
    }
    cout << "  While-loop sum of 0..3: " << whileSum << endl;

    int doCounter = 0;
    do {
        doCounter = doCounter + 1;
    } while (doCounter < 3);
    cout << "  Do-While final counter: " << doCounter << endl;
    cout << endl;

    // Test 4: Switch-Case & Enums
    cout << "[TEST 4] Enums & Switch-Case Statement:" << endl;
    int currentSubject = COMPUTING;
    cout << "  Subject Code: " << currentSubject << " -> ";
    switch (currentSubject) {
        case 1:
            cout << "Mathematics" << endl;
            break;
        case 2:
            cout << "Science" << endl;
            break;
        case 3:
            cout << "Computer Science" << endl;
            break;
        default:
            cout << "Unknown Subject" << endl;
            break;
    }
    cout << endl;

    // Test 5: Namespaces & Clamping
    cout << "[TEST 5] Namespaces & Utility Functions:" << endl;
    int rawVal = 105;
    int clamped = Analytics::clampScore(rawVal, 0, 100);
    int squareVal = Analytics::computeSquare(6);
    cout << "  Clamped 105 to [0, 100] = " << clamped << endl;
    cout << "  Square of 6 = " << squareVal << endl;
    cout << endl;

    // Test 6: Function Templates
    cout << "[TEST 6] Function Templates:" << endl;
    int maxInt = findMax(45, 92);
    int minInt = findMin(45, 92);
    cout << "  Template findMax(45, 92) = " << maxInt << endl;
    cout << "  Template findMin(45, 92) = " << minInt << endl;
    cout << endl;

    // Test 7: Object-Oriented Programming (Polymorphism & V-Tables)
    cout << "[TEST 7] OOP, Virtual Methods, & Polymorphism:" << endl;
    Student undergrad(80, 90);
    undergrad.setId(101);

    GraduateStudent grad(95);
    grad.setId(102);

    Participant* p1 = (Participant*)&undergrad;
    Participant* p2 = (Participant*)&grad;

    int score1 = p1->evaluate();
    int score2 = p2->evaluate();

    cout << "  Undergrad ID: " << p1->getId() << " -> Evaluated Score: " << score1 << " (Avg of 80, 90)" << endl;
    cout << "  Grad Student ID: " << p2->getId() << " -> Evaluated Score: " << score2 << " (Thesis 95)" << endl;
    cout << endl;

    // Test 8: Operator Overloading
    cout << "[TEST 8] Operator Overloading:" << endl;
    BonusCalculator calc(BONUS_POINTS);
    int totalBonus = calc + 15;
    cout << "  Base bonus (" << BONUS_POINTS << ") + 15 via operator+ = " << totalBonus << endl;
    if (calc == 10) {
        cout << "  operator== check: Matches expected 10 points." << endl;
    }
    cout << endl;

    // Test 9: Recursion & Function Overloading
    cout << "[TEST 9] Recursion & Function Overloading:" << endl;
    int fact5 = factorial(5);
    cout << "  Factorial of 5 = " << fact5 << " (Expected: 120)" << endl;

    int intPoints = calculateGradePoints(85);
    double doublePoints = calculateGradePoints(3.8);
    cout << "  Overloaded grade points for int 85 = " << intPoints << endl;
    cout << "  Overloaded grade points for double 3.8 = " << doublePoints << endl;
    cout << endl;

    // Test 10: Exception Handling (try / catch / throw)
    cout << "[TEST 10] Exception Handling (try / catch / throw):" << endl;
    int caughtCode = 0;
    try {
        cout << "  Validating test score: -10" << endl;
        int checkScore = -10;
        if (checkScore < 0) {
            throw 99; // Exception 99: Out of range score
        }
        cout << "  [ERROR] Should not reach here!" << endl;
    } catch (int err) {
        caughtCode = err;
        cout << "  Successfully caught exception code: " << err << " (Invalid Score Handled)" << endl;
    }
    cout << endl;

    // Test 11: Deliberately Unoptimized Code (Optimization Engine Showcase)
    cout << "[TEST 11] Optimizer Engine Showcase (Constant Folding, DCE, Unrolling):" << endl;
    int optResult = demonstrateOptimization();
    cout << "  Demonstration Function Computed Result: " << optResult << " (Expected: 220)" << endl;
    cout << "  [HINT] Compile with: python main.py build test.cpp -O2 --verbose" << endl;
    cout << "         to see the optimizer report folded constants and removed dead code!" << endl;
    cout << endl;

    // Final Summary
    cout << "============================================================" << endl;
    cout << "       ALL 11 COMPILER SUBSYSTEM CHECKS COMPLETED!          " << endl;
    cout << "============================================================" << endl;

    return 0;
}
