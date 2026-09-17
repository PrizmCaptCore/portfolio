import React from "react";
import Image from "next/image";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "./ui/dialog";
import { VisuallyHidden } from "./ui/visually-hidden";
import { About } from "./About";

interface LogoProps {
    isCollapsed: boolean;
}

const Logo = React.forwardRef<HTMLButtonElement, LogoProps>(({ isCollapsed }, ref) => {
  return (
    <Dialog aria-describedby={undefined}>
      {isCollapsed ? (
        <DialogTrigger asChild>
          <button ref={ref} className="flex items-center justify-start mb-2 cursor-pointer bg-transparent border-none p-0 hover:opacity-80 transition-opacity">
            <Image src="/icon_128x128.png" alt="로고" width={40} height={40} />
          </button>
        </DialogTrigger>
      ) : (
        <div className="w-full min-w-0 px-1 py-1 text-center">
          <DialogTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center justify-center bg-transparent hover:opacity-80"
            >
              <Image
                src="/sidebar-title-logo.png"
                alt="Relay Assistant"
                width={200}
                height={50}
                className="h-auto w-[200px] max-w-full"
                unoptimized
                quality={100}
                priority
              />
            </button>
          </DialogTrigger>
        </div>
      )}
      <DialogContent>
        <VisuallyHidden>
          <DialogTitle>Relay Assistant 정보</DialogTitle>
        </VisuallyHidden>
        <About />
      </DialogContent>
    </Dialog>
  );
});

Logo.displayName = "Logo";

export default Logo;