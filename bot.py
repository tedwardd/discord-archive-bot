import os
import re
import logging
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from urllib.parse import urlparse

from database import init_db, add_watched_site, remove_watched_site, get_watched_sites, is_watched_site
from archive_service import ArchiveService
from renderer import ArchiveRenderer

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# URL regex pattern
URL_PATTERN = re.compile(
    r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*',
    re.IGNORECASE
)


class ArchiveBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        
        # Use slash commands only (prefix set to unused value)
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        
        self.archive_service = ArchiveService()
        self.archive_renderer = ArchiveRenderer()
    
    async def setup_hook(self):
        """Called when the bot is starting up."""
        await init_db()
        await self.add_cog(SiteManagementCog(self))
        await self.add_cog(ArchiveCog(self))
        # Sync slash commands
        await self.tree.sync()
    
    async def close(self):
        """Cleanup when bot shuts down."""
        await self.archive_service.close()
        await self.archive_renderer.close()
        await super().close()


class SiteManagementCog(commands.Cog, name="Site Management"):
    """Commands for managing the watched sites list."""
    
    def __init__(self, bot: ArchiveBot):
        self.bot = bot
    
    @commands.hybrid_command(name="addsite", description="Add a domain to the watched sites list")
    @app_commands.describe(domain="The domain to add (e.g., nytimes.com)")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def add_site(self, ctx: commands.Context, domain: str):
        """Add a domain to the watched sites list."""
        # Clean up the domain
        domain = domain.lower().strip()
        if domain.startswith("http"):
            parsed = urlparse(domain)
            domain = parsed.netloc
        
        # Remove www. prefix if present
        if domain.startswith("www."):
            domain = domain[4:]
        
        if not domain:
            await ctx.send("Please provide a valid domain.")
            return
        
        added = await add_watched_site(str(ctx.guild.id), domain, str(ctx.author))
        if added:
            await ctx.send(f"Added `{domain}` to the watched sites list.")
        else:
            await ctx.send(f"`{domain}` is already in the watched sites list.")
    
    @commands.hybrid_command(name="removesite", description="Remove a domain from the watched sites list")
    @app_commands.describe(domain="The domain to remove")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def remove_site(self, ctx: commands.Context, domain: str):
        """Remove a domain from the watched sites list."""
        domain = domain.lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]
        
        removed = await remove_watched_site(str(ctx.guild.id), domain)
        if removed:
            await ctx.send(f"Removed `{domain}` from the watched sites list.")
        else:
            await ctx.send(f"`{domain}` was not in the watched sites list.")
    
    @commands.hybrid_command(name="listsites", description="List all sites being monitored for archiving")
    @commands.guild_only()
    async def list_sites(self, ctx: commands.Context):
        """List all domains in the watched sites list."""
        sites = await get_watched_sites(str(ctx.guild.id))
        
        if not sites:
            await ctx.send("No sites are currently being monitored.")
            return
        
        # Format the list nicely
        site_list = "\n".join(f"• `{site}`" for site in sites)
        
        embed = discord.Embed(
            title="Monitored Sites",
            description=site_list,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Total: {len(sites)} sites")
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(name="archivehelp", description="Show Archive Bot commands")
    async def archive_help(self, ctx: commands.Context):
        """Show help for Archive Bot commands."""
        embed = discord.Embed(
            title="Archive Bot Help",
            description="Automatically detects URLs from watched sites and creates archived versions.",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="/archive <url>",
            value="Get archive.today links for any URL",
            inline=False
        )
        embed.add_field(
            name="/render <url>",
            value="Create an archived version of a URL",
            inline=False
        )
        embed.add_field(
            name="/listsites",
            value="List all monitored sites",
            inline=False
        )
        embed.add_field(
            name="/addsite <domain>",
            value="Add a site to watch (requires Manage Messages)",
            inline=False
        )
        embed.add_field(
            name="/removesite <domain>",
            value="Remove a watched site (requires Manage Messages)",
            inline=False
        )
        
        await ctx.send(embed=embed)


class ArchiveCog(commands.Cog, name="Archive"):
    """Commands and listeners for archive functionality."""
    
    def __init__(self, bot: ArchiveBot):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for messages containing URLs from watched sites."""
        # Ignore bot messages and DMs
        if message.author.bot or not message.guild:
            return
        
        # Find all URLs in the message
        urls = URL_PATTERN.findall(message.content)
        
        if not urls:
            return
        
        watched_sites = await get_watched_sites(str(message.guild.id))
        if not watched_sites:
            return
        
        for url in urls:
            try:
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                
                # Remove www. prefix for matching
                if domain.startswith("www."):
                    domain = domain[4:]
                
                # Check if this domain matches any watched site
                is_watched = any(
                    watched_domain in domain or domain in watched_domain
                    for watched_domain in watched_sites
                )
                
                if is_watched:
                    await self._handle_watched_url(message, url)
                    
            except Exception as e:
                print(f"Error processing URL {url}: {e}")
    
    async def _handle_watched_url(self, message: discord.Message, url: str):
        """Handle a URL from a watched site by rendering an archive."""
        # Send initial status message
        embed = discord.Embed(
            title="Archiving Page",
            description="Creating an archived version of this page. This may take a few minutes...",
            color=discord.Color.orange()
        )
        status_msg = await message.reply(embed=embed, mention_author=False)
        
        # Render the archive
        result = await self.bot.archive_renderer.render_archive(url)
        
        if result.success and result.archive_url:
            embed = discord.Embed(
                title="Archived Version",
                description="Successfully created an archived version.",
                color=discord.Color.green()
            )
            embed.add_field(name="Archive URL", value=result.archive_url, inline=False)
        else:
            # Provide manual links on failure
            links = self.bot.archive_service.get_links(url)
            embed = discord.Embed(
                title="Archive Failed",
                description="Could not automatically archive this page.",
                color=discord.Color.red()
            )
            embed.add_field(
                name="Archive Manually",
                value=f"[Search existing archives]({links.search_url}) or [create new archive]({links.save_url})",
                inline=False
            )
        
        await status_msg.edit(embed=embed)
    
    @commands.hybrid_command(name="archive", description="Get archive.today links for a URL")
    @app_commands.describe(url="The URL to get archive links for")
    async def manual_archive(self, ctx: commands.Context, url: str):
        """Get archive.today links for a URL."""
        if not url.startswith("http"):
            url = "https://" + url
        
        links = self.bot.archive_service.get_links(url)
        
        embed = discord.Embed(
            title="Archive Links",
            description="Use these links to find or create an archived version.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Search Existing Archives", value=links.search_url, inline=False)
        embed.add_field(name="Create New Archive", value=links.save_url, inline=False)
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(name="render", description="Create an archived version of a URL")
    @app_commands.describe(url="The URL to archive")
    async def render_archive(self, ctx: commands.Context, url: str):
        """Create an archived version of a URL on archive.today."""
        logger.info(f"!render command received for URL: {url}")
        
        if not url.startswith("http"):
            url = "https://" + url
        
        await ctx.defer()
        
        embed = discord.Embed(
            title="Archiving Page",
            description="Creating an archived version of this page. This may take a few minutes...",
            color=discord.Color.orange()
        )
        status_msg = await ctx.send(embed=embed)
        
        logger.info("Starting archive_renderer.render_archive...")
        result = await self.bot.archive_renderer.render_archive(url)
        logger.info(f"render_archive completed. Success: {result.success}, Error: {result.error}")
        
        if result.success and result.archive_url:
            embed = discord.Embed(
                title="Archive Created",
                description="Successfully created an archived version.",
                color=discord.Color.green()
            )
            embed.add_field(name="Archive URL", value=result.archive_url, inline=False)
        else:
            links = self.bot.archive_service.get_links(url)
            embed = discord.Embed(
                title="Archive Failed",
                description="Could not automatically archive this page.",
                color=discord.Color.red()
            )
            embed.add_field(
                name="Archive Manually",
                value=f"[Search existing archives]({links.search_url}) or [create new archive]({links.save_url})",
                inline=False
            )
        
        await status_msg.edit(embed=embed)


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("Error: DISCORD_TOKEN environment variable not set.")
        print("Please copy .env.example to .env and add your bot token.")
        return
    
    bot = ArchiveBot()
    bot.run(token)


if __name__ == "__main__":
    main()
