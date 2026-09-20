# syntax=docker/dockerfile:1

# Restore and publish. Alpine is safe here because the app sets
# InvariantGlobalization, so it needs no ICU.
FROM mcr.microsoft.com/dotnet/sdk:8.0-alpine AS build
WORKDIR /source

# The csproj is copied on its own first so the restore layer is reused
# whenever only the source files change.
COPY src/FileServe/FileServe.csproj FileServe/
RUN dotnet restore FileServe/FileServe.csproj

COPY src/FileServe/ FileServe/
RUN dotnet publish FileServe/FileServe.csproj -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0-alpine AS runtime
WORKDIR /app
COPY --from=build /app .

# Mount point for the folder being served. It is deliberately outside /app:
# the app refuses to start if the vault overlaps its own directory.
RUN mkdir -p /data

ENV ASPNETCORE_HTTP_PORTS=8080 \
    FileVault__RootPath=/data

EXPOSE 8080

# Nothing is written at runtime, so the process does not need to be root.
# APP_UID (1654) is the non-root user the .NET base images ship with.
USER $APP_UID

# wget comes from busybox in the alpine image.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["dotnet", "FileServe.dll"]
