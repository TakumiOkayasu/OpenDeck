#include "opendeck/model.hpp"

extern "C" int helper(void);

int main() {
    const opendeck::Slot slot{"consumer"};
    return helper() == 7 && slot.name == "consumer" ? 0 : 1;
}
