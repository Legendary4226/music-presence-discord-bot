from enum import StrEnum

class CommandEnum(StrEnum):
    ROLE = "role"
    ROLES = "roles"
    JOINED = "joined"
    LISTENING = "listening"
    STOP = "stop"
    LOGS = "logs"
    HELP = "help"

    def description(self) -> str:
        return {
            self.ROLE: "Set or unset the role to give to active Music Presence listeners that have the specified roles",
            self.ROLES: "List all listener roles and their respective parent roles",
            self.JOINED: "Check the join time of yourself or another user with some extras",
            self.LISTENING: "Register your currently active listening status for the listener role",
            self.STOP: "Stop the bot and remove the listener role from all members in all servers",
            self.LOGS: "Tells you where the Music Presence logs are located",
            self.HELP: "Use this command if you need help with Music Presence",
        }[self]
