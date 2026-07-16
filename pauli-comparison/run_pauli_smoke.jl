#!/usr/bin/env julia

using Dates
using Pkg
using SHA

try
    import PauliPropagation
catch err
    println(stderr, "Could not load PauliPropagation in the active Julia project.")
    println(stderr, "Run:")
    println(stderr, "  julia --project=pauli-comparison -e 'using Pkg; Pkg.instantiate()'")
    rethrow(err)
end

function usage()
    return """
    Usage:
      julia --project=pauli-comparison pauli-comparison/run_pauli_smoke.jl \\
        --nqubits 32 --pauli Z --index 16 --repeat 1000 --output smoke.json
    """
end

function parse_args(argv)
    parsed = Dict{String,String}(
        "nqubits" => "32",
        "pauli" => "Z",
        "index" => "16",
        "repeat" => "1",
        "output" => "pauli_smoke.json",
    )

    i = 1
    while i <= length(argv)
        arg = argv[i]
        if arg == "--help" || arg == "-h"
            println(usage())
            exit(0)
        end
        if !startswith(arg, "--")
            error("Unexpected positional argument: $arg")
        end
        key = arg[3:end]
        if !haskey(parsed, key)
            error("Unknown option: $arg")
        end
        if i == length(argv)
            error("Missing value for option: $arg")
        end
        parsed[key] = argv[i + 1]
        i += 2
    end
    return parsed
end

function iso_utc_now()
    return Dates.format(now(UTC), dateformat"yyyy-mm-ddTHH:MM:SS.sssZ")
end

function file_sha256(path::AbstractString)
    isfile(path) || return nothing
    return bytes2hex(open(SHA.sha256, path))
end

function package_version(name::String)
    for (_, dep) in Pkg.dependencies()
        if dep.name == name
            return dep.version === nothing ? nothing : string(dep.version)
        end
    end
    return nothing
end

function json_escape(s::AbstractString)
    out = IOBuffer()
    for c in s
        if c == '"'
            print(out, "\\\"")
        elseif c == '\\'
            print(out, "\\\\")
        elseif c == '\n'
            print(out, "\\n")
        elseif c == '\r'
            print(out, "\\r")
        elseif c == '\t'
            print(out, "\\t")
        elseif Int(c) < 0x20
            print(out, "\\u", lpad(string(Int(c), base=16), 4, '0'))
        else
            print(out, c)
        end
    end
    return String(take!(out))
end

function json_value(x)
    if x === nothing
        return "null"
    elseif x isa Bool
        return x ? "true" : "false"
    elseif x isa Integer || x isa AbstractFloat
        return string(x)
    elseif x isa AbstractString
        return "\"" * json_escape(x) * "\""
    elseif x isa AbstractVector
        return "[" * join((json_value(v) for v in x), ", ") * "]"
    elseif x isa AbstractDict
        parts = String[]
        for key in sort(collect(keys(x)))
            push!(parts, json_value(string(key)) * ": " * json_value(x[key]))
        end
        return "{" * join(parts, ", ") * "}"
    else
        return json_value(string(x))
    end
end

function write_json(path::AbstractString, payload)
    parent = dirname(path)
    if !isempty(parent)
        mkpath(parent)
    end
    open(path, "w") do io
        print(io, json_value(payload))
        print(io, "\n")
    end
end

function main(argv)
    args = parse_args(argv)
    nqubits = parse(Int, args["nqubits"])
    index = parse(Int, args["index"])
    repeat = parse(Int, args["repeat"])
    pauli_token = uppercase(args["pauli"])

    if nqubits <= 0
        error("--nqubits must be positive")
    end
    if index < 1 || index > nqubits
        error("--index must be in 1:nqubits")
    end
    if repeat <= 0
        error("--repeat must be positive")
    end
    if !(pauli_token in ("X", "Y", "Z"))
        error("--pauli must be one of X, Y, Z")
    end

    pauli_symbol = Symbol(pauli_token)
    started_at = iso_utc_now()

    observable = nothing
    observable_string = ""
    GC.gc()
    t0 = time_ns()
    for _ in 1:repeat
        observable = PauliPropagation.PauliString(nqubits, pauli_symbol, index)
        observable_string = string(observable)
    end
    elapsed_ns = time_ns() - t0
    ended_at = iso_utc_now()

    project_path = Base.active_project()
    manifest_path = project_path === nothing ? nothing : joinpath(dirname(project_path), "Manifest.toml")
    payload = Dict{String,Any}(
        "schema_version" => 1,
        "created_at_utc" => ended_at,
        "started_at_utc" => started_at,
        "ended_at_utc" => ended_at,
        "julia" => Dict{String,Any}(
            "version" => string(VERSION),
            "project" => project_path,
            "manifest" => manifest_path,
            "project_sha256" => project_path === nothing ? nothing : file_sha256(project_path),
            "manifest_sha256" => manifest_path === nothing ? nothing : file_sha256(manifest_path),
        ),
        "packages" => Dict{String,Any}(
            "PauliPropagation" => package_version("PauliPropagation"),
        ),
        "parameters" => Dict{String,Any}(
            "nqubits" => nqubits,
            "pauli" => pauli_token,
            "index" => index,
            "repeat" => repeat,
        ),
        "timing" => Dict{String,Any}(
            "total_s" => elapsed_ns / 1.0e9,
            "mean_s" => (elapsed_ns / 1.0e9) / repeat,
        ),
        "result" => Dict{String,Any}(
            "observable" => observable_string,
            "observable_type" => observable === nothing ? nothing : string(typeof(observable)),
        ),
    )
    write_json(args["output"], payload)
    println(args["output"])
end

main(ARGS)
