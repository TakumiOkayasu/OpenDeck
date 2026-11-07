#include "opendeck/model.hpp"

static_assert(__cplusplus == 202302L, "Consumers must receive the C++23 language mode");

extern "C" int helper(void);

int main() {
    const opendeck::Slot slot{"consumer"};
    return helper() == 7 && slot.name == "consumer" ? 0 : 1;
}
