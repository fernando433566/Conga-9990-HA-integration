"""Small bounded LZ4 block decoder written from the public block format.

Format reference: https://github.com/lz4/lz4/blob/dev/doc/lz4_Block_format.md
No implementation code from LZ4 or the robot application is included here.
"""


class LZ4DecodeError(ValueError):
    """Malformed or oversized compressed block."""


def decompress_block(data: bytes, max_output: int) -> bytes:
    if max_output < 0:
        raise ValueError("max_output must be nonnegative")
    output = bytearray()
    position = 0

    def length(base):
        nonlocal position
        result = base
        if base == 15:
            while True:
                if position >= len(data):
                    raise LZ4DecodeError("Truncated extended length")
                part = data[position]
                position += 1
                result += part
                if result > max_output:
                    raise LZ4DecodeError("Output limit exceeded")
                if part != 255:
                    break
        return result

    while position < len(data):
        token = data[position]
        position += 1
        literals = length(token >> 4)
        if position + literals > len(data):
            raise LZ4DecodeError("Truncated literal sequence")
        if len(output) + literals > max_output:
            raise LZ4DecodeError("Output limit exceeded")
        output.extend(data[position:position + literals])
        position += literals
        if position == len(data):
            return bytes(output)
        if position + 2 > len(data):
            raise LZ4DecodeError("Truncated match offset")
        offset = data[position] | data[position + 1] << 8
        position += 2
        if offset == 0 or offset > len(output):
            raise LZ4DecodeError("Invalid match offset")
        count = length(token & 15) + 4
        if len(output) + count > max_output:
            raise LZ4DecodeError("Output limit exceeded")
        # Repeated reads support overlapping matches, including offset one.
        for _ in range(count):
            output.append(output[-offset])
    raise LZ4DecodeError("Block has no final literal sequence")
