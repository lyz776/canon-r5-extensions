/* Synthetic QEMU-only code. Contains no Canon firmware or camera entry points.
 * MODE: 0=ARM, 1=Thumb-16, 2=Thumb-32 scalar transfers.
 * FAULT: 0=normal, 1/2=unmapped load/store, 3/4=unaligned load/store.
 */
.syntax unified
.cpu cortex-a9
.section .text
.global _start
.arm
_start:
    /* MMU off, low vectors, ARM exception entry; enable alignment faults. */
    mrc p15, 0, r0, c1, c0, 0
    bic r0, r0, #1
    bic r0, r0, #(1 << 13)
    bic r0, r0, #(1 << 30)
    orr r0, r0, #2
    mcr p15, 0, r0, c1, c0, 0
    ldr r0, =vectors
    mcr p15, 0, r0, c12, c0, 0
    isb
.if FAULT == 1 || FAULT == 2
    /* Zero RAM supplies an empty L1 table. Map only the ROM code section.
     * These are synthetic guest page tables, not R5 firmware addresses.
     */
    ldr r0, =0x7800
    ldr r1, =0xe0000c02
    str r1, [r0]
    ldr r0, =0x4000
    mcr p15, 0, r0, c2, c0, 0
    mov r0, #0
    mcr p15, 0, r0, c2, c0, 2
    mov r0, #1
    mcr p15, 0, r0, c3, c0, 0
    mrc p15, 0, r0, c1, c0, 0
    orr r0, r0, #1
    mcr p15, 0, r0, c1, c0, 0
    isb
.endif
    ldr r2, =0x10000
.if MODE != 0
    adr r0, exercise + 1
    bx r0
    .thumb
.endif
exercise:
.if FAULT != 0
.if FAULT >= 3
    adds r2, #1
.endif
    movs r3, #0x5a
.if FAULT == 1 || FAULT == 3
.if MODE == 2
    ldr.w r4, [r2]
.else
    ldr r4, [r2]
.endif
.else
.if MODE == 2
    str.w r3, [r2]
.else
    str r3, [r2]
.endif
.endif
    b fail
.else
    /* Immediate offsets: byte, halfword, signed halfword, full word. */
    movs r3, #0xa5
.if MODE == 2
    strb.w r3, [r2]
    ldrb.w r4, [r2]
.else
    strb r3, [r2]
    ldrb r4, [r2]
.endif
    cmp r4, r3
    bne fail
    movs r3, #0x80
    lsls r3, r3, #8
    adds r3, #1
.if MODE == 2
    strh.w r3, [r2, #2]
    ldrh.w r4, [r2, #2]
.else
    strh r3, [r2, #2]
    ldrh r4, [r2, #2]
.endif
    cmp r4, r3
    bne fail
    movs r5, #2
.if MODE == 2
    ldrsh.w r4, [r2, r5]
.else
    ldrsh r4, [r2, r5]
.endif
    ldr r5, =0xffff8001
    cmp r4, r5
    bne fail
    ldr r3, =0x12345678
.if MODE == 2
    str.w r3, [r2, #4]
    ldr.w r4, [r2, #4]
.else
    str r3, [r2, #4]
    ldr r4, [r2, #4]
.endif
    cmp r4, r3
    bne fail
    /* Register offset and destination/base overlap. */
    movs r5, #8
.if MODE == 2
    str.w r3, [r2, r5]
    ldr.w r4, [r2, r5]
.else
    str r3, [r2, r5]
    ldr r4, [r2, r5]
.endif
    cmp r4, r3
    bne fail
    adds r5, r2, #4
.if MODE == 2
    ldr.w r5, [r5]
.else
    ldr r5, [r5]
.endif
    cmp r5, r3
    bne fail
    /* Multiple transfers also exercise the older logging wrappers. */
    movs r3, #0x11
    movs r4, #0x22
    adds r2, #16
    stmia r2!, {r3, r4}
    subs r2, #8
    ldmia r2!, {r5, r6}
    cmp r5, r3
    bne fail
    cmp r6, r4
    bne fail
    b success
.endif
fail:
.if MODE != 0
    adr r0, arm_fail
    bx r0
    .balign 4
    .arm
.endif
arm_fail:
    mov r0, #0x18
    mov r1, #1
    svc 0x123456
    b .
.if MODE != 0
    .thumb
.endif
success:
.if MODE != 0
    adr r0, arm_success
    bx r0
    .balign 4
    .arm
.endif
arm_success:
    mov r0, #4
    ldr r1, =message
    svc 0x123456
    mov r0, #0x18
    ldr r1, =0x20026
    svc 0x123456
    b .

.balign 32
vectors:
    b arm_fail
    b arm_fail
    b arm_fail
    b arm_fail
    b data_abort
    b arm_fail
    b arm_fail
    b arm_fail
data_abort:
.if FAULT != 0
    /* Require the intended fault type and faulting address. */
    mrc p15, 0, r0, c5, c0, 0
    and r1, r0, #0xf
.if FAULT <= 2
    cmp r1, #5
.else
    cmp r1, #1
.endif
    bne arm_fail
    tst r0, #(1 << 10)
    bne arm_fail
    mrc p15, 0, r0, c6, c0, 0
.if FAULT <= 2
    ldr r1, =0x10000
.else
    ldr r1, =0x10001
.endif
    cmp r0, r1
    bne arm_fail
    b arm_success
.else
    b arm_fail
.endif
.ltorg
message:
    .asciz "SYNTHETIC R5 CPU/RAM OK\n"
