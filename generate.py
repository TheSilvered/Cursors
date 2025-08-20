"""
.cur file structure

Notes:
- basically an .ico file but there is not .png support
  - images are stored in .bmp without the BITMAPHEADER
- numbers are stored in little endian

1) ICONDIR
Offset  Size  Name        Description
-------------------------------------
     0     2  idReserved  Always 0
     2     2  idType      Always 2 (1 specifies .ico files)
     4     2  idCount     Number of images in the file

2) ICONDIRENTRY * idCount
Offset  Size  Name           Description
----------------------------------------
     0     1  bWidth         Image width (0 becomes 256)
     1     1  bHeight        Image height (0 becomes 256)
     2     1  bColorCount    Number of colors in palette (0 if not used and if >= 8bpp)
     3     1  bReserved      Always 0
     4     2  wPlanes        Cursor hotspot X (pixels from the left)
     6     2  wBitCount      Cursor hotspot Y (pixels from the top)
     8     4  dwBytesInRes   Number of bytes in the pixel data
    12     4  dwImageOffset  Offset from the beginning of the file of the pixel data

3) Image pixel data in BMP format
Name      Description
---------------------
icHeader  DIB header
icColors  Image colors in BGRA format
icXOR     Empty
icAND     Bit mask: 1 = transparent pixel, 0 = use color

3.1) BITMAPINFOHEADER
Offset  Size  Name             Descritpion
------------------------------------------
     0     4  biSize           Header size (= 40)
     4     4  biWidth          Image width in pixels
     8     4  biHeight         Image height in pixels * 2
    12     2  biPlanes         = 1
    14     2  biBitCount       = 32
    16     4  biCompression    Not used, = 0
    20     4  biSizeImage      Image size in bytes (size of icColors + icAND)
    24     4  biXPelsPerMeter  Not used, = 0
    28     4  biYPelsPerMeter  Not used, = 0
    32     4  biClrUsed        Not used, = 0
    36     4  biClrImportant   Not used, = 0

.ani file structure

Notes:
- a RIFF file with many icons inside, each icon is a frame
  - these are normal icons: .png's are supported
- numbers are stored in little endian

Definitions:
- SEQUENCE = 0x2 // Flag which allows for a sequence of indices to be used (allows frames to be used multiple times)

1) RIFF chunk header
Offset  Size  Name       Description
------------------------------------
     0     4  id         Chunk id (= 'RIFF')
     4     4  chunkSize  Size of the chunk (except id and chunkSize = fileSize - 8)
     8     4  dataForm   Type of data contained (= 'ACON')

2) anih chunk
Offset  Size  Name       Description
------------------------------------
     0     4  id         Chunk id (= 'anih')
     4     4  chunkSize  Size of the chunk (except id and chunkSize = 36)
     8    36  aniHeader  Ani header

2.1) Ani header
Offset  Size  Name       Description
------------------------------------
     0     4  cbSizeof   Size of the header (= 36)
     4     4  cFrames    Number of frames in the list
     8     4  cSteps     Number of frames in the animation (the same as cFrames if SEQUENCE is not set)
    12     4  cx         Not used, = 0
    16     4  cy         Not used, = 0
    20     4  cBitCount  Not used, = 0
    24     4  cPlanes    Not used, = 0
    28     4  jifRate    Default display rate in 1/60s (jiffies)
    32     4  flags      1's bit always set, optionally SEQUENCE

3) 'rate' and 'seq ' chunks when SEQUENCE is set

3.1) 'rate' chunk
Offset       Size  Name       Description
-----------------------------------------
     0          4  id         Chunk id (= 'rate')
     4          4  chunkSize  Size of the chunk (cFrames * 4)
     8  4*cFrames  rates      An array of jiffies for each image

3.2) 'seq ' chunk
Offset      Size  Name       Description
----------------------------------------
     0         4  id         Chunk id (= 'seq ', notice the space)
     4         4  chunkSize  Size of the chunk (cFrames * 4)
     8  4*cSteps  indices    An array of image indices to indicate what image to display on each frame

4) LIST chunk of frames
Offset  Size  Name       Description
------------------------------------
     0     4  id         Chunk id (= 'LIST')
     4     4  chunkSize  Size of the chunk (except id and chunkSize)
     8     4  listType   Type of the list (= 'fram')
    12     ?  iconData   Images of the animation (.ico files)

5) iconData

Like in .cur files this will contain a ICONDIR and multiple ICONDIRENTRY's.
The pixel data can either be in BMP format or in PNG format.

Each image is an 'icon' block

"""

import asyncio
from dataclasses import dataclass
from enum import Enum, auto
from io import BytesIO
import os
import os.path
import shutil
from typing import Collection, NoReturn
import xml.etree.ElementTree as xml

# Utility functions
def u32(x: int) -> bytes: return x.to_bytes(4, "little")
def i32(x: int) -> bytes: return x.to_bytes(4, "little", signed=True)
def u16(x: int) -> bytes: return x.to_bytes(2, "little")
def u8(x: int) -> bytes: return x.to_bytes(1, "little")

def gray(s: str) -> str: return "\x1b[90m" + s + "\x1b[0m"
def red(s: str) -> str: return "\x1b[91m" + s + "\x1b[0m"
def yellow(s: str) -> str: return "\x1b[33m" + s + "\x1b[0m"

try:
    from PIL import Image
except ImportError as e:
    e.add_note(red("Package 'pillow' is required."))
    raise e


class CursorError(Exception):
    """Exception raised when creating a `Cursor` object fails."""
    pass


class Cursor:
    @dataclass
    class AniCfg:
        frame_count: int
        frame_rate: int
        frame_list: list[int] | None
        rate_list: list[int] | None

    @dataclass
    class Hotspot:
        x: float
        y: float

    def __init__(self, path: str):
        self.path = path
        if self.path[-4:] != ".svg":
            self.__error("expected an SVG image")
        if not os.path.isfile(path):
            self.__error(f"{path} is not a file")
        self.name = os.path.basename(path)[:-4]
        self.hotspot, self.ani_cfg = self.__get_info()

    def is_ani(self):
        return self.ani_cfg is not None

    def __warning(self, msg: str) -> None:
        print(yellow(f"{self.path}: {msg}"))

    def __error(self, msg: str) -> NoReturn:
        print(red(f"{self.path}: {msg}"))
        raise CursorError(f"{self.path}: {msg}")

    def __get_info(self) -> tuple[Hotspot, AniCfg | None]:
        svg_tree = xml.parse(self.path).getroot()
        width_attr = svg_tree.attrib.get("width")
        height_attr = svg_tree.attrib.get("height")

        x_attr = None
        y_attr = None
        ani_cfg_str = None

        for element in svg_tree:
            if element.get('id') == 'hotspot' and element.tag.endswith('rect'):
                x_attr = element.get('x')
                y_attr = element.get('y')
            elif element.get('id') == 'ani_config' and element.tag.endswith('text'):
                ani_cfg_str = element.text

        hotspot = self.__parse_hotspot(width_attr, height_attr, x_attr, y_attr)
        ani_cfg = self.__parse_ani_cfg(ani_cfg_str) if ani_cfg_str is not None else None

        return hotspot, ani_cfg

    def __parse_hotspot(
            self,
            width_attr: str | None,
            height_attr: str | None,
            x_attr: str | None,
            y_attr: str | None
    ) -> Hotspot:
        if width_attr is None or height_attr is None:
            self.__error("failed to query SVG size")
        try:
            width = int(width_attr)
            height = int(height_attr)
        except ValueError:
            self.__error("failed to query SVG size")

        if x_attr is None or y_attr is None:
            self.__warning("missing hotspot")

        if x_attr is None:
            x = 0
        else:
            try:
                x = int(x_attr)
            except ValueError:
                self.__warning("invalid hotspot X position")
                x = 0

        if y_attr is None:
            y = 0
        else:
            try:
                y = int(y_attr)
            except ValueError:
                self.__warning("invalid hotspot Y position")
                y = 0

        if x < 0 or y < 0 or x > width or y > height:
            self.__warning("the hotspot is outside of the drawing")

        x = min(max(x / width, 0), 1)
        y = min(max(y / height, 0), 1)

        return self.Hotspot(x, y)

    def __parse_ani_cfg(self, cfg_str: str) -> AniCfg:
        items = cfg_str.strip().removesuffix(";").split(";")
        str_cfg = {}

        opt_name: str
        str_value: str

        # Parse the key-value pairs

        for item in items:
            if "=" not in item:
                self.__warning(f"option is missing value '{item}', format: optionName=value")
                continue
            opt_name, str_value = item.split("=")
            str_cfg[opt_name.strip()] = str_value.strip()

        final_cfg = {}

        # Parse the values themselves

        for opt_name, str_value in str_cfg.items():
            if opt_name in ("frameCount", "frameRate"):
                try:
                    value = self.__parse_int(str_value)
                except ValueError:
                    self.__warning(f"invalid value '{str_value}' for option '{opt_name}'")
                    continue
            elif opt_name in ("frameList", "rateList"):
                try:
                    value = [self.__parse_int(n) for n in str_value.removesuffix(",").split(",")]
                except ValueError:
                    self.__warning(f"invalid value '{str_value}' for option '{opt_name}'")
                    continue
            else:
                self.__warning(f"unknown option '{opt_name}'")
                continue

            final_cfg[opt_name] = value

        # Check for correctness in the values themselves

        if "frameCount" not in final_cfg:
            self.__error(f"missing required option 'frameCount'")
        if final_cfg["frameCount"] == 0:
            self.__error(f"'frameCount' cannot be zero")

        if "frameList" in final_cfg:
            frame_list = final_cfg["frameList"]
            for frame in frame_list:
                if frame >= final_cfg["frameCount"]:
                    self.__error(f"frame index {frame} is too big")

        if final_cfg.get("frameRate", 1) == 0:
            self.__warning("'frameRate' cannot be zero")
            final_cfg["frameRate"] = 1

        expected_rate_len = final_cfg["frameCount"]
        if "rateList" in final_cfg:
            rate_list: list[int] = final_cfg["rateList"]
            zero_rate = False
            for i, rate in enumerate(rate_list):
                if rate == 0:
                    zero_rate = True
                    rate_list[i] = 1

            if zero_rate:
                self.__warning("no rate in 'rateList' can be zero")

            if len(rate_list) != expected_rate_len:
                self.__warning(f"'rateList' was expected to have {expected_rate_len} elements but had {len(rate_list)}")

            if len(rate_list) < expected_rate_len:
                rate_list.extend([final_cfg.get("frameRate", 1)] * (expected_rate_len - len(rate_list)))
            elif len(rate_list) > expected_rate_len:
                final_cfg["rateList"] = rate_list[:expected_rate_len]

        return self.AniCfg(
            frame_count=final_cfg["frameCount"],
            frame_rate=final_cfg.get("frameRate", 1),
            frame_list=final_cfg.get("frameList"),
            rate_list=final_cfg.get("rateList")
        )

    @staticmethod
    def __parse_int(s: str) -> int:
        value = int(s)
        if value < 0 or value >= 2**32:
            raise ValueError
        return value


class CursorGenerator:
    """
    CUR and ANI file generator, generates a cursor file from an SVG.

    The hotspot of the cursor is (0, 0) by default. It can be changed by adding
    a rect with the ID 'hotspot' at the root of the SVG.

    By default a static cursor is generated. To generate an animated one add a
    text object at the root of the SVG with the ID 'ani_config' which contains
    the following options:

    - `frameCount: int`: the total number of unique frames in the file
    - `frameRate: int` (optional): the display rate of the animation in 1/60 of
      a second, by default it is 1
    - `frameList: list[int]` (optional): a comma separated list of frame
      indices to use instead of the sequencial ordering of the frames
    - `rateList: list[int]` (optional): a comma separated list of frame rates
      to use instead of `frameRate`

    Ani config example: `frameCount=3;frameRate=2;frameList=1,2,3,2`

    Each frame is a layer with the id `frame_[index]` with `index` starting from
    `1`.

    An optional `static` layer can be added to animated files that will always
    be exported.

    Needs Inkscape. The name of the cursor is taken from the source file.
    The intermediate PNGs are store in 'png_out_dir'.
    """

    class Result(Enum):
        SUCCESS = auto()
        FAILED = auto()
        INKSCAPE_BUG = auto()

    def __init__(self, src: Cursor, png_out_dir: str, cur_out_dir: str, resolutions: Collection[int] = (32, 48, 64)):
        self.src = src
        self.png_out_dir = os.path.join(png_out_dir, self.src.name)
        self.cur_out_dir = cur_out_dir
        if self.src.is_ani():
            self.cur_file = os.path.join(self.cur_out_dir, f"{self.src.name}.ani")
        else:
            self.cur_file = os.path.join(self.cur_out_dir, f"{self.src.name}.cur")

        self.resolutions = resolutions

    def __is_inkscape_bug(self, s: str) -> Result:
        if s.strip() == "terminate called after throwing an instance of 'Gio::DBus::Error'":
            return self.Result.INKSCAPE_BUG
        else:
            return self.Result.FAILED

    async def __gen_ani_pngs(self) -> bool:
        assert self.src.ani_cfg is not None

        process = await asyncio.create_subprocess_exec(
            "inkscape",
            self.src.path,
            "--query-id=static",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()

        has_static_layer = len(stderr.decode().strip()) == 0

        actions = []
        out_files = []

        for res in self.resolutions:
            out_file_dir = os.path.join(self.png_out_dir, f"{res}")
            os.makedirs(out_file_dir, exist_ok=True)
            out_files.append(out_file_dir + f"[1..{self.src.ani_cfg.frame_count}].png")

            if has_static_layer:
                out_file = os.path.join(out_file_dir, f"static.png")
                actions.extend([
                    f"export-filename:{out_file}",
                    f"export-width:{res}",
                    f"export-height:{res}",
                    f'export-id:static',
                    "export-id-only",
                    "export-area-page",
                    "export-do"
                ])

            for i in range(self.src.ani_cfg.frame_count):
                out_file = os.path.join(out_file_dir, f"{i}.png")
                actions.extend([
                    f"export-filename:{out_file}",
                    f"export-width:{res}",
                    f"export-height:{res}",
                    f'export-id:frame_{i + 1}',
                    "export-id-only",
                    "export-area-page",
                    "export-do"
                ])

        if len(out_files) == 0:
            return self.Result.SUCCESS

        print(f"Generating {', '.join(out_files)}...")

        process = await asyncio.create_subprocess_exec(
            "inkscape",
            self.src.path,
            "--actions=" + ";".join(actions),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            print(red(f"Generation of {', '.join(out_files)} failed"))
            stderr_str = stderr.decode().strip()
            stdout_str = stdout.decode().strip()
            if stderr_str:
                print(gray("stderr: " + stderr_str))
            if stdout_str:
                print(gray("stdout: " + stdout_str))
            return self.__is_inkscape_bug(stderr_str)

        return self.Result.SUCCESS

    async def __gen_pngs(self) -> bool:
        os.makedirs(self.png_out_dir, exist_ok=True)

        actions = []
        out_files = []

        for res in self.resolutions:
            out_file = os.path.join(self.png_out_dir, f"{res}.png")
            actions.extend([
                f"export-filename:{out_file}",
                f"export-width:{res}",
                f"export-height:{res}",
                "export-area-page",
                "export-do"
            ])
            out_files.append(out_file)

        if len(out_files) == 0:
            return self.Result.SUCCESS

        print(f"Generating {', '.join(out_files)}...")

        process = await asyncio.create_subprocess_exec(
            "inkscape",
            self.src.path,
            "--actions=" + ";".join(actions),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0 or not all(map(os.path.exists, out_files)):
            print(red(f"Generation of {', '.join(out_files)} failed"))
            stderr_str = stderr.decode().strip()
            stdout_str = stdout.decode().strip()
            if stderr_str:
                print(gray("stderr: " + stderr_str))
            if stdout_str:
                print(gray("stdout: " + stdout_str))
            return self.__is_inkscape_bug(stderr_str)

        return self.Result.SUCCESS

    def __gen_ico_bytes(self, images: list[Image.Image]) -> bytes:
        assert len(images) == len(self.resolutions)

        icondir = bytearray()
        icondir.extend(u16(0))
        icondir.extend(u16(2))
        icondir.extend(u16(len(self.resolutions)))

        image_bytes = []
        for image, res in zip(images, self.resolutions):
            image_bytes.append(self.__gen_bitmap(image, res))


        entries = []
        ENTRY_SIZE = 16
        min_offset = len(icondir) + ENTRY_SIZE*len(self.resolutions)

        for i, res in enumerate(self.resolutions):
            hotspotX = int(res * self.src.hotspot.x)
            hotspotY = int(res * self.src.hotspot.y)
            image_offset = min_offset + sum(map(len, image_bytes[:i]))
            entry = bytearray()
            entry.extend(u8(res))                   # bWidth
            entry.extend(u8(res))                   # bHeight
            entry.extend(u8(0))                     # bColorCount
            entry.extend(u8(0))                     # bReserved
            entry.extend(u16(hotspotX))             # wPlanes (hotspotX)
            entry.extend(u16(hotspotY))             # wBitCount (hotspotY)
            entry.extend(u32(len(image_bytes[i])))  # dwBytesInRes
            entry.extend(u32(image_offset))         # dwImageOffset
            entries.append(entry)

        ico_file = bytearray()
        ico_file.extend(icondir)
        for entry in entries:
            ico_file.extend(entry)
        for img in image_bytes:
            ico_file.extend(img)

        return ico_file

    @staticmethod
    def __gen_bitmap(image: Image.Image, res: int) -> bytearray:
        image = image.convert("RGBA")
        assert image.width == res and image.height == res

        bgra_table_size = res * res * 4
        if res * res % 8 == 0:
            and_mask_size = res * res // 8
        else:
            and_mask_size = res * res // 8 + 1
        and_mask_size += and_mask_size & 1  # make image_size even (to end at a WORD boundary)

        image_size = bgra_table_size + and_mask_size

        image_data = bytearray()

        # BITMAPINFOHEADER
        image_data.extend(u32(40))               # biSize
        image_data.extend(i32(image.width))      # biWidth
        image_data.extend(i32(image.height * 2)) # biHeight
        image_data.extend(u16(1))                # biPlanes
        image_data.extend(u16(32))               # biBitCount
        image_data.extend(u32(0))                # biCompression
        image_data.extend(u32(image_size))       # biImageSize
        image_data.extend(u32(0))                # biXPelsPerMeter
        image_data.extend(u32(0))                # biYPelsPerMeter
        image_data.extend(u32(0))                # biClrUsed
        image_data.extend(u32(0))                # biClrImportant

        # Pixel colors (row by row from bottom to top and left to right)
        mask = ""
        for y in range(res - 1, -1, -1):
            for x in range(res):
                pixel = image.getpixel((x, y))
                assert type(pixel) is tuple
                r, g, b, a = pixel
                if a == 0:
                    r = g = b = 0
                    mask += "1"
                else:
                    mask += "0"
                image_data.extend(u8(b))
                image_data.extend(u8(g))
                image_data.extend(u8(r))
                image_data.extend(u8(a))
        del image
        mask += "0" * (len(mask) - and_mask_size * 8)

        # Add the AND mask
        for mask_byte in range(and_mask_size):
            byte = mask[mask_byte * 8:(mask_byte+1) * 8]
            byte = int(byte, 2)
            image_data.extend(u8(byte))

        return image_data

    def __gen_cur(self):
        print(f"Generating {self.cur_file}...")

        os.makedirs(self.cur_out_dir, exist_ok=True)

        images = []
        for res in self.resolutions:
            img_path = os.path.join(self.png_out_dir, f"{res}.png")
            images.append(Image.open(img_path))

        with open(self.cur_file, "wb") as cur:
            cur.write(self.__gen_ico_bytes(images))

    def __gen_ani(self):
        assert self.src.ani_cfg is not None

        print(f"Generating {self.cur_file}...")

        riff_block = bytearray()
        riff_block.extend("RIFF".encode("ascii"))

        anih_block = bytearray()
        anih_block.extend("anih".encode("ascii"))  # id
        anih_block.extend(u32(36))                 # chunkSize

        if self.src.ani_cfg.frame_list is None:
            steps = self.src.ani_cfg.frame_count
        else:
            steps = len(self.src.ani_cfg.frame_list)

        if self.src.ani_cfg.frame_list is not None or self.src.ani_cfg.rate_list is not None:
            flags = 1 | 2
        else:
            flags = 1

        # aniHeader
        anih_block.extend(u32(36))                            # cbSizeof
        anih_block.extend(u32(self.src.ani_cfg.frame_count))  # cFrames
        anih_block.extend(u32(steps))                         # cSteps
        anih_block.extend(u32(0))                             # cx
        anih_block.extend(u32(0))                             # cy
        anih_block.extend(u32(0))                             # cBitCount
        anih_block.extend(u32(0))                             # cPlanes
        anih_block.extend(u32(self.src.ani_cfg.frame_rate))   # jifRate
        anih_block.extend(u32(flags))                         # flags

        rate_block = bytearray()
        seq_block = bytearray()

        if flags != 1:
            rate_block.extend("rate".encode("ascii"))
            rate_block.extend(u32(self.src.ani_cfg.frame_count * 4))

            if self.src.ani_cfg.rate_list is not None:
                for rate in self.src.ani_cfg.rate_list:
                    rate_block.extend(u32(rate))
            else:
                rate = self.src.ani_cfg.frame_rate
                for _ in range(self.src.ani_cfg.frame_count):
                    rate_block.extend(u32(rate))

            seq_block.extend("seq ".encode("ascii"))
            seq_block.extend(u32(steps * 4))
            if self.src.ani_cfg.frame_list is not None:
                for idx in self.src.ani_cfg.frame_list:
                    seq_block.extend(u32(idx))
            else:
                for i in range(steps):
                    rate_block.extend(u32(i))

        frame_list = bytearray()
        frame_list.extend("LIST".encode("ascii"))

        frames: list[bytes] = []

        for i in range(self.src.ani_cfg.frame_count):
            images = []
            for res in self.resolutions:
                frame_image_path = os.path.join(self.png_out_dir, f"{res}/{i}.png")
                static_image_path = os.path.join(self.png_out_dir, f"{res}/static.png")
                frame_image = Image.open(frame_image_path)
                if os.path.isfile(static_image_path):
                    static_image = Image.open(static_image_path)
                    composite = Image.new("RGBA", (res, res))
                    composite.paste(static_image)
                    composite.paste(frame_image, mask=frame_image)
                    frame_image = composite
                images.append(frame_image)

            image_bytes = self.__gen_ico_bytes(images)
            frame_block = bytearray()
            frame_block.extend("icon".encode("ascii"))
            frame_block.extend(u32(len(image_bytes)))
            frame_block.extend(image_bytes)
            frames.append(frame_block)

        frame_list.extend(u32(4 + sum(map(len, frames))))
        frame_list.extend("fram".encode("ascii"))
        for frame in frames:
            frame_list.extend(frame)

        riff_block_size = (
            4
            + len(anih_block)
            + len(seq_block)
            + len(rate_block)
            + len(frame_list)
        )

        riff_block.extend(u32(riff_block_size))
        riff_block.extend("ACON".encode("ascii"))
        riff_block.extend(anih_block)
        riff_block.extend(rate_block)
        riff_block.extend(seq_block)
        riff_block.extend(frame_list)

        with open(self.cur_file, "wb") as cur:
            cur.write(riff_block)

    async def generate(self) -> Result:
        src_file_mtime = os.path.getmtime(self.src.path)
        # Only generate the file if the SVG is newer than the CUR
        if os.path.exists(self.cur_file) and os.path.getmtime(self.cur_file) > src_file_mtime:
            return self.Result.SUCCESS

        if self.src.is_ani():
            result = await self.__gen_ani_pngs()
            if result != self.Result.SUCCESS:
                return result
            self.__gen_ani()
        else:
            result = await self.__gen_pngs()
            if result != self.Result.SUCCESS:
                return result
            self.__gen_cur()
        return self.Result.SUCCESS


async def main():
    if shutil.which("inkscape") is None:
        print(red("Inkscape is required to use 'generate.py'"))
        exit(1)

    coroutines = []
    for file in os.listdir("svgs"):
        try:
            cursor = Cursor(os.path.join("svgs", file))
        except CursorError:
            continue
        generator = CursorGenerator(
            cursor,
            png_out_dir="pngs",
            cur_out_dir="cursors",
            resolutions=(32, 48, 64)
        )
        coroutines.append(generator.generate)


    # Inkscape crashes if it is run too many times in parallel
    max_concurrent_tasks = 5
    i = 0
    while i < len(coroutines):
        gather_coroutines = coroutines[i:i + max_concurrent_tasks]
        results = await asyncio.gather(*(c() for c in gather_coroutines))
        success_count = sum(list(map(lambda x: x == CursorGenerator.Result.SUCCESS, results)))
        max_concurrent_tasks = success_count
        i += success_count

        # Re-run failed images
        coroutines.extend([c for c, r in zip(gather_coroutines, results) if r == CursorGenerator.Result.INKSCAPE_BUG])

    # Copy other files
    shutil.copy("templates/scripts/install.inf", "cursors/install.inf")
    shutil.copy("templates/scripts/uninstall.cmd", "cursors/uninstall.cmd")
    shutil.copy("LICENSE.txt", "cursors/LICENSE.txt")


if __name__ == "__main__":
    asyncio.run(main())
