#include "src/memory_profile.h"
#include <cassert>
#include <thread>

int main(int argc, char **argv) {
  using namespace memory_profile;
  assert(argc == 2);
  const std::filesystem::path dir(argv[1]);
  std::istringstream pressure("some avg10=0.00 total=123000\nfull avg10=0.00 total=45000\n");
  auto parsed = parse_pressure(pressure);
  assert(parsed && parsed->some_us == 123000 && parsed->full_us == 45000);
  for (const std::string bad : {"some total=0\n", "some total=-1\nfull total=0\n",
                                "some total=abc\nfull total=0\n"}) {
    std::istringstream input(bad);
    assert(!parse_pressure(input));
  }
  const auto resolve = [](const std::string &group, const std::string &mount) {
    std::istringstream cgroup(group), mounts(mount);
    return pressure_path(cgroup, mounts).string();
  };
  assert(resolve("0::/pod/worker\n", "1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n")
         == "/sys/fs/cgroup/pod/worker/memory.pressure");
  assert(resolve("0::/\n", "1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n")
         == "/sys/fs/cgroup/memory.pressure");
  assert(resolve("0::/pod/worker\n", "1 0 0:1 /pod /cg rw - cgroup2 cgroup rw\n")
         == "/cg/worker/memory.pressure");
  assert(resolve("0::/pod2/worker\n", "1 0 0:1 /pod /cg rw - cgroup2 cgroup rw\n").empty());
  assert(resolve("0::/../outside\n", "1 0 0:1 / /cg rw - cgroup2 cgroup rw\n").empty());
  assert(resolve("1:memory:/pod\n", "1 0 0:1 / /cg rw - cgroup cgroup rw\n").empty());
  assert(unescape_mount_path("/path\\040with\\134escape") == "/path with\\escape");

  std::ofstream(dir / "cgroup") << "0::/\n";
  std::ofstream(dir / "mounts") << "1 0 0:1 / " << dir.string() << " rw - cgroup2 cgroup rw\n";
  std::ofstream(dir / "memory.pressure") << "some total=100000\nfull total=50000\n";
  Profile profile(dir / "cgroup", dir / "mounts");
  std::this_thread::sleep_for(std::chrono::milliseconds(30));
  std::ofstream(dir / "memory.pressure") << "some total=105000\nfull total=52000\n";
  profile.write(dir / "available.json");
  std::ofstream(dir / "memory.pressure") << "some total=0\nfull total=0\n";
  profile.write(dir / "reset.json");
  std::filesystem::remove(dir / "memory.pressure");
  profile.write(dir / "end_missing.json");
  Profile missing(dir / "cgroup", dir / "mounts");
  missing.write(dir / "unavailable.json");
}
