# Host build of prep/ + its test driver: make -C tests/prep  ->  build/host_prep
ROOT := ../..
AAC  := $(ROOT)/third_party/vo-aacenc
SRC  := host_prep.c $(ROOT)/prep/source/prep.c $(wildcard $(ROOT)/codec/source/*.c) \
        $(wildcard $(AAC)/aacenc/src/*.c) $(wildcard $(AAC)/aacenc/basic_op/*.c) $(AAC)/common/cmnMemory.c
INC  := -I$(ROOT)/prep/include -I$(ROOT)/codec/include -I$(ROOT)/tools/r3dconv -I$(ROOT)/third_party/minih264 \
        -I$(AAC)/aacenc/inc -I$(AAC)/aacenc/basic_op -I$(AAC)/common/include

$(ROOT)/build/host_prep: ENCODER_SRC = $(SRC)
$(ROOT)/build/host_prep_padded: ENCODER_SRC = $(subst $(ROOT)/prep/source/prep.c,padded_reference.c,$(SRC))
$(ROOT)/build/host_prep $(ROOT)/build/host_prep_padded: $(SRC) $(ROOT)/prep/include/prep.h
	@mkdir -p $(@D)
	$(CC) $(CPPFLAGS) -O2 -w $(INC) $(ENCODER_SRC) -lm -lpthread -o $@

$(ROOT)/build/host_prep_padded: padded_reference.c
